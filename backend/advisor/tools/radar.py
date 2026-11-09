"""Bounded recruitment-radar search tool."""
from langchain_core.callbacks.manager import adispatch_custom_event
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import Field
from typing import Annotated

from ..radar.client import enrich_jobs, search_jobs


@tool
async def search_recruitment_radar(query: str, intent: dict, config: RunnableConfig,
    limit: Annotated[int, Field(ge=1, le=40)] = 24,
    read_limit: Annotated[int, Field(ge=0, le=10)] = 5) -> dict:
    """从实时公开招聘汇总、企业官网、公众号固定公告和导入数据检索岗位。

    intent填写用户明确条件及语义展开岗位；保留招聘类别、城市、企业和时间范围。
    返回招聘汇总线索及已读官网正文；源表更新日期不等于公告发布日期。
    """
    async def publish(phase, **fields):
        await adispatch_custom_event("recruitment_progress", {"phase": phase, **fields}, config=config)
    return await search_jobs(intent, query, limit=limit, read_limit=read_limit, publish=publish)


@tool
async def verify_recruitment_radar_candidates(jobs: list[dict], config: RunnableConfig,
    read_limit: Annotated[int, Field(ge=1, le=40)] = 20) -> dict:
    """对已通过岗位语义初筛的候选读取公告及官网，优先补齐最终展示项，不读取已排除岗位。"""
    async def publish(phase, **fields):
        await adispatch_custom_event("recruitment_progress", {"phase": phase, **fields}, config=config)
    return {"jobs": await enrich_jobs(jobs, read_limit=read_limit, publish=publish), "status": "ok"}
