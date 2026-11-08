"""Local recruitment-radar data management and streaming collection endpoints."""
import asyncio
from contextlib import suppress
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import client as radar

router = APIRouter()
UI = Path(__file__).resolve().parents[2] / "tools" / "recruitment_radar"
OPERATION = asyncio.Lock()


class ImportInput(BaseModel):
    filename: str = Field(max_length=200)
    content: str = Field(max_length=3_000_000)


class CrawlInput(BaseModel):
    industry: str = Field(default="", max_length=100)
    keyword: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=856)


@router.get("/radar")
async def index():
    return FileResponse(UI / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/radar/app.js")
async def javascript():
    return FileResponse(UI / "app.js", media_type="application/javascript", headers={"Cache-Control": "no-store"})


@router.get("/api/radar/status")
async def status():
    return {**radar.capabilities(), "running": OPERATION.locked(), "industries": sorted({site["industry"] for site in radar.catalog()}),
            "provenance": {"repository": "https://github.com/jiabaobei/xiaozhao-radar", "commit": "5615418132c4affb3c689eb1fc603e12d1c112a8", "license": "Apache-2.0"}}


@router.get("/api/radar/sites")
async def sites(industry: str = "", keyword: str = ""):
    rows = [site for site in radar.catalog() if (not industry or site["industry"] == industry)
            and (not keyword or keyword.casefold() in (site["company"] + site["industry"]).casefold())]
    return {"count": len(rows), "sites": rows}


@router.get("/api/radar/jobs")
async def jobs(keyword: str = "", city: str = "", industry: str = "", source: str = "",
               page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200)):
    data = radar.read_jobs()
    rows = [job for job in data["jobs"] if (not city or city.casefold() in job["city"].casefold())
            and (not industry or job["industry"] == industry) and (not source or job["source_type"] == source)
            and (not keyword or all(term in " ".join(radar.text(job.get(k)) for k in ("company", "role", "city", "batch", "industry")).casefold()
                                     for term in keyword.casefold().split()))]
    return {"jobs": rows[(page - 1) * page_size:page * page_size], "total": len(rows), "all_records": len(data["jobs"]),
            "mode": data["mode"], "fetched_at": data["fetched_at"], "limitations": data["limitations"], "page": page, "page_size": page_size}


@router.post("/api/radar/import")
async def import_data(payload: ImportInput):
    try:
        rows = radar.import_records(payload.content, payload.filename)
    except (ValueError, TypeError, AttributeError) as error:
        raise HTTPException(422, "导入失败：需要有效的JSON岗位数组或CSV表格，最多10000条、3MB") from error
    if not rows:
        raise HTTPException(422, "文件中没有可识别的公司或岗位字段")
    async with radar.WRITE_LOCK:
        previous = radar.read_json(radar.STATE / "imports.json", {}).get("jobs", [])
        combined = radar.deduplicate([*previous, *rows])
        radar.write_json(radar.STATE / "imports.json", {"jobs": combined})
    return {"status": "ok", "imported": len(rows), "added": len(combined) - len(previous), "stored": len(combined)}


async def stream_operation(operation):
    if OPERATION.locked():
        raise HTTPException(409, "已有数据采集正在运行，请等待完成或停止。")
    await OPERATION.acquire()
    async def stream():
        queue = asyncio.Queue()
        async def publish(phase, **fields):
            await queue.put({"type": "progress", "phase": phase, **fields})
        async def execute():
            try:
                result = await operation(publish)
                if "jobs" in result:
                    result = {key: value for key, value in result.items() if key != "jobs"}
                await queue.put({"type": "result", "result": result})
            except Exception as error:
                await queue.put({"type": "error", "message": f"采集未完成（{type(error).__name__}），已保留现有数据。"})
        task = asyncio.create_task(execute())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 10)
                except asyncio.TimeoutError:
                    event = {"type": "heartbeat"}
                yield json.dumps(event, ensure_ascii=False) + "\n"
                if event["type"] in {"result", "error"}:
                    break
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            OPERATION.release()
    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


@router.post("/api/radar/sync")
async def sync():
    return await stream_operation(lambda publish: radar.sync_jobs(force=True, publish=publish))


@router.post("/api/radar/crawl")
async def crawl(payload: CrawlInput):
    return await stream_operation(lambda publish: radar.crawl_sites(**payload.model_dump(), publish=publish))
