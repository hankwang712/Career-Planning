"""Recruitment aggregation, bounded official-site extraction and CLI imports.

Public data parsing is ported from xiaozhao-radar, Apache-2.0; see vendor/LICENSE.
No shared upstream API key, public CORS proxy, or automatic CAPTCHA solver is used.
"""
import asyncio
import base64
import csv
from datetime import datetime, timedelta
from html.parser import HTMLParser
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import threading
from urllib.parse import urljoin, urlsplit
import uuid
import zlib

import httpx

from .vendor.sync_tencent_docs import field_value, is_expired, map_industry, parse_sheet
from ..utils.recruitment_dates import publication_state
from .job_sources import deduplicate_jobs, read_jobhunter_jobs

ROOT = Path(__file__).resolve().parent
STATE = ROOT.parents[2] / "data" / "app_data" / "recruitment-radar"
DOCUMENT = "https://docs.qq.com/smartsheet/DTkRMUVhoUWJXZEhJ"
SHEETS = [("tTNjGc", "27届内推汇总", 900), ("tvVDZj", "实习提前批每日更新", 6000),
          ("tK4q9U", "日常实习补充汇总", 900)]
class CrossLoopLock:
    """Reports run in separate asyncio.run loops/threads; share resources without loop-bound locks."""
    def __init__(self):
        self._lock = threading.Lock()
    async def __aenter__(self):
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(0.05)
        return self
    async def __aexit__(self, *args):
        self._lock.release()


SYNC_LOCK = CrossLoopLock()
WRITE_LOCK = CrossLoopLock()
BROWSER_LOCK = CrossLoopLock()
USER_AGENT = "Mozilla/5.0 RecruitmentRadar/1.0"


def text(value, limit=4000):
    return str(value or "").strip()[:limit]


def public_url(value):
    value = text(value, 3000)
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or parsed.port not in (None, 80, 443):
            return ""
        try:
            if not ipaddress.ip_address(host).is_global:
                return ""
        except ValueError:
            pass
        return value
    except ValueError:
        return ""


async def validate_target(url):
    if not public_url(url):
        raise ValueError("仅允许公开HTTP/HTTPS网址")
    host = urlsplit(url).hostname
    addresses = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("不允许访问本机或内网地址")


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix("." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def catalog():
    return read_json(ROOT / "data/sites.json", [])


def normalize_job(row, *, source_type="import", source_name="导入数据", snapshot_at=""):
    def pick(*keys):
        return next((text(row[k]) for k in keys if row.get(k) is not None and text(row[k])), "")
    job = {
        "company": pick("company", "c", "公司名称"), "role": pick("role", "p", "position", "title", "招聘岗位"),
        "city": pick("city", "l", "location", "district", "工作地点"), "degree": pick("degree", "e", "学历"),
        "batch": pick("batch", "w", "批次"), "deadline": pick("deadline", "d", "招聘截止日期"),
        "url": public_url(pick("url", "u", "投递链接or推文", "投递链接")),
        "announcement_url": public_url(pick("announcement_url", "官方公告")),
        "updated_at": pick("updated_at", "更新日期", "更新时间"),
        "published_at": pick("published_at", "datePosted", "发布日期", "发布时间", "公告发布日期", "招聘发布日期"),
        "industry": pick("industry", "ind", "行业") or "综合", "source_type": source_type,
        "source_name": source_name, "snapshot_at": snapshot_at,
        "description": pick("description", "content", "正文"),
        "source_sheet": pick("source_sheet"), "detail_state": "not_read",
    }
    if not job["role"] and not job["company"]:
        return None
    job["role"] = job["role"] or "招聘信息（岗位待核实）"
    return job


def deduplicate(jobs):
    return deduplicate_jobs(jobs)


def read_jobs():
    live = read_json(STATE / "live.json", {})
    limitations = []
    if live.get("jobs"):
        jobs = live["jobs"]
        mode = "live_cache"
        limitations.extend(live.get("limitations", []))
    else:
        snapshot = read_json(ROOT / "data/snapshot.json", {})
        jobs = [normalize_job(row, source_type="snapshot", source_name="校招雷达仓库快照", snapshot_at=snapshot.get("updated", "")) for row in snapshot.get("jobs", [])]
        mode = "snapshot"
        limitations.append(f"当前使用{snapshot.get('updated', '日期未知')}的仓库快照，不能据此确认岗位近期发布或仍开放。")
    imported = read_json(STATE / "imports.json", {}).get("jobs", [])
    crawled = read_json(STATE / "crawled.json", {}).get("jobs", [])
    return {"jobs": deduplicate([*jobs, *imported, *crawled]), "mode": mode,
            "fetched_at": live.get("fetched_at"), "limitations": limitations}


def capabilities():
    return {"ready": True, "name": "校招雷达", "message": "腾讯文档招聘汇总、856个采集节点及本地数据已接入",
        "sites": len(catalog()), "records": len(read_jobs()["jobs"]),
        "firecrawl": bool(os.getenv("RADAR_FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")),
        "anysearch": bool(os.getenv("ANYSEARCH_API_KEY") or os.getenv("RADAR_ANYSEARCH_ENABLED") == "1"),
        "cli_import": True, "automatic_cli_execution": False}


async def fetch_sheet(client, sheet_id, end):
    params = {"u":"", "noEscape":"1", "enableSmartsheetSplit":"1", "supportOptimizedVer":"4",
        "chunkCellSize":"15000", "normal":"1", "outformat":"1", "wb":"1", "nowb":"0", "callback":"x",
        "xsrf":"", "id":"DTkRMUVhoUWJXZEhJ", "subId":sheet_id, "startrow":"0", "endrow":str(end)}
    response = await client.get("https://docs.qq.com/dop-api/opendoc", params=params,
        headers={"Referer": DOCUMENT, "User-Agent": USER_AGENT})
    response.raise_for_status()
    match = re.match(r"^[^(]*\((.*)\)\s*;?\s*$", response.text, re.S)
    if not match:
        raise ValueError("腾讯文档未返回预期的数据格式")
    payload = json.loads(match.group(1))
    parts = payload.get("clientVars", {}).get("collab_client_vars", {}).get("initialAttributedText", {}).get("text") or []
    encoded = parts[0].get("smartsheet") if parts and isinstance(parts[0], dict) else None
    if not encoded:
        raise ValueError("腾讯文档未返回公开表格内容，可能需要登录或结构已变化")
    encoded = re.sub(r"\s+", "", encoded)
    return parse_sheet(zlib.decompress(base64.b64decode(encoded + "=" * (-len(encoded) % 4))).decode("utf-8"))


async def sync_jobs(force=False, publish=None):
    async with SYNC_LOCK:
        previous = read_json(STATE / "live.json", {})
        synced_ids = {sheet.get("sheet_id") for sheet in previous.get("sheets", []) if sheet.get("status") == "ok"}
        complete_sheets = {sheet_id for sheet_id, _, _ in SHEETS} <= synced_ids
        if not force and previous.get("jobs") and complete_sheets:
            try:
                if datetime.now().astimezone() - datetime.fromisoformat(previous["fetched_at"]) < timedelta(hours=6):
                    return {**read_jobs(), "status": "cached", "sync": previous.get("sheets", [])}
            except (ValueError, KeyError):
                pass
        summaries, fresh, failures = [], [], []
        async with httpx.AsyncClient(timeout=35, trust_env=False) as client:
            for sheet_id, name, cap in SHEETS:
                records, seen = [], set()
                error = None
                for end in range(300, cap + 1, 300):
                    if publish:
                        await publish("sync", title=name, reason=f"读取公开招聘汇总表，范围0—{end}")
                    try:
                        rows = await fetch_sheet(client, sheet_id, end)
                    except (httpx.HTTPError, ValueError, KeyError, zlib.error) as exc:
                        error = f"{name}读取未完成（{type(exc).__name__}）"
                        failures.append(error)
                        break
                    added = 0
                    for row in rows:
                        key = json.dumps(row, sort_keys=True, ensure_ascii=False)
                        if key not in seen:
                            records.append(row)
                            seen.add(key)
                            added += 1
                    if not added:
                        break
                else:
                    failures.append(f"{name}已达到本轮{cap}行读取上限，覆盖可能不完整")
                for row in records:
                    job = normalize_job(row, source_type="aggregate", source_name="腾讯文档公开招聘汇总")
                    if job:
                        job["source_sheet"] = name
                        fresh.append(job)
                if error:
                    fresh.extend(job for job in previous.get("jobs", []) if job.get("source_sheet") == name)
                summaries.append({"sheet_id": sheet_id, "sheet": name, "records": len(records), "status": "partial" if error else "ok", "error": error})
        if fresh:
            saved = {"fetched_at": datetime.now().astimezone().isoformat(), "jobs": deduplicate(fresh), "sheets": summaries,
                     "limitations": failures}
            write_json(STATE / "live.json", saved)
        data = read_jobs()
        data["limitations"] = list(dict.fromkeys([*data["limitations"], *failures]))
        return {**data, "status": "partial" if failures else "ok", "sync": summaries}


def import_records(content, filename):
    if len(content.encode("utf-8")) > 3_000_000:
        raise ValueError("导入文件不能超过3MB")
    raw = content.lstrip("\ufeff").strip()
    if filename.lower().endswith(".csv"):
        rows = list(csv.DictReader(io.StringIO(raw)))
    else:
        value = json.loads(raw)
        if not isinstance(value, (dict, list)):
            raise ValueError("JSON必须是对象或数组")
        rows = value if isinstance(value, list) else value.get("jobs", value.get("items", value.get("data", [])))
    if not isinstance(rows, list) or len(rows) > 10000 or any(not isinstance(row, dict) for row in rows):
        raise ValueError("需要JSON记录数组或CSV表格，最多10000条")
    normalized = [normalize_job(row, source_type="import", source_name="CLI/文件导入") for row in rows]
    return [job for job in normalized if job]


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.links, self.metadata = [], [], {}
        self.skip = 0
        self.anchor = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self.skip += 1
        if tag in {"p", "div", "li", "h1", "h2", "h3", "br", "tr", "section"}:
            self.parts.append("\n")
        if tag == "a":
            self.anchor = [attrs.get("href", ""), []]
        if tag == "meta":
            self.metadata[attrs.get("property") or attrs.get("name") or ""] = attrs.get("content", "")
    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self.skip:
            self.skip -= 1
        if tag == "a" and self.anchor:
            self.links.append({"url": self.anchor[0], "text": "".join(self.anchor[1]).strip()})
            self.anchor = None
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.anchor:
                self.anchor[1].append(data)


class ArticleParser(PageParser):
    """Read WeChat's article container, excluding navigation and embedded scripts."""
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.images = []
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if values.get("id") == "js_content":
            self.depth = 1
        elif self.depth and tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.depth += 1
        if self.depth:
            super().handle_starttag(tag, attrs)
            if tag == "img":
                src = values.get("data-src") or values.get("src")
                if src:
                    self.images.append(src)
    def handle_endtag(self, tag):
        if self.depth:
            super().handle_endtag(tag)
            self.depth -= 1
    def handle_data(self, data):
        if self.depth:
            super().handle_data(data)
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in {"img", "br", "hr", "input", "meta", "link", "source", "wbr"}:
            self.handle_endtag(tag)


def page_publication(html, metadata):
    """Only explicit publication fields; never infer publication from crawling/update time."""
    from .browser import _publication
    for key in ("article:published_time", "datePublished", "date", "pubdate", "publishdate", "publish_time"):
        if metadata.get(key):
            value = metadata[key]
            parsed = _publication(value, value)
            if parsed:
                return parsed
    match = re.search(r'\b(?:ct|create_time)\s*[:=]\s*["\']?(\d{10,13})\b', html)
    if match:
        return _publication(match[1], "") or ""
    match = re.search(r'id=["\']publish_time["\'][^>]*>([^<]+)', html)
    if match:
        parsed = _publication("", match[1])
        if parsed:
            return parsed
    match = re.search(r'["\']datePublished["\']\s*:\s*["\']([^"\']+)', html)
    return (_publication("", match[1]) or "") if match else ""


async def direct_extract(url):
    async with httpx.AsyncClient(timeout=16, trust_env=False, headers={"User-Agent": USER_AGENT}) as client:
        for _ in range(6):
            await validate_target(url)
            async with client.stream("GET", url) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers.get("location", ""))
                    continue
                response.raise_for_status()
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 12_000_000:
                        raise ValueError("页面超过12MB读取上限")
                html = bytes(data).decode(response.encoding or "utf-8", "replace")
                parser = PageParser()
                parser.feed(html)
                images = []
                if urlsplit(url).hostname == "mp.weixin.qq.com":
                    article = ArticleParser()
                    article.feed(html)
                    parser.parts, parser.links = article.parts, article.links
                    images = list(dict.fromkeys(urljoin(url, src) for src in article.images if public_url(urljoin(url, src))))
                content = re.sub(r"[ \t]+", " ", "".join(parser.parts))
                content = re.sub(r"\n\s*\n+", "\n", content).strip()
                if re.search(r"验证码|环境异常|访问过于频繁|安全验证", content) and len(content) < 1500:
                    raise ValueError("页面要求验证，未取得有效正文")
                links = [{**link, "url": urljoin(url, link["url"])} for link in parser.links if public_url(urljoin(url, link["url"]))]
                published = page_publication(html, parser.metadata)
                return {"content": content[:60000], "truncated": len(content) > 60000,
                        "image_urls": images, "image_count": len(images), "links": links[:300], "url": url,
                        "published_at": published, "method": "direct_http"}
        raise ValueError("页面重定向次数过多")


async def provider_extract(url, provider):
    await validate_target(url)
    async with httpx.AsyncClient(timeout=45, trust_env=False) as client:
        if provider == "firecrawl":
            key = os.getenv("RADAR_FIRECRAWL_API_KEY") or os.getenv("FIRECRAWL_API_KEY")
            if not key:
                raise ValueError("Firecrawl未配置密钥")
            response = await client.post("https://api.firecrawl.dev/v1/scrape", headers={"Authorization": "Bearer " + key},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True})
            response.raise_for_status()
            data = response.json().get("data", {})
            markdown = data.get("markdown", "")
            return {"content": markdown[:60000], "truncated": len(markdown) > 60000,
                    "image_urls": list(dict.fromkeys(re.findall(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", markdown))), "links": [], "url": url,
                    "published_at": data.get("metadata", {}).get("publishedTime", ""), "method": provider}
        headers = {"Content-Type": "application/json"}
        if os.getenv("ANYSEARCH_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["ANYSEARCH_API_KEY"]
        response = await client.post("https://api.anysearch.com/mcp", headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "extract", "arguments": {"url": url}}})
        response.raise_for_status()
        data = response.json()
        if data.get("error") or data.get("result", {}).get("isError"):
            raise ValueError("AnySearch返回抽取错误")
        content = "\n".join(block.get("text", "") for block in data.get("result", {}).get("content", []) if block.get("type") == "text")
        return {"content": content[:60000], "truncated": len(content) > 60000,
                "image_urls": list(dict.fromkeys(re.findall(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", content))),
                "links": [], "url": url, "published_at": "", "method": provider}


def browser_extract(url):
    from .browser import _BrowserSession, _read_article
    with _BrowserSession() as browser:
        pending = browser.pending_verification()
        if pending and urlsplit(pending["url"]).hostname == urlsplit(url).hostname:
            return {"status": "blocked", "content": "", "links": [], "url": url, "verification": pending,
                    "error": "同一网站的验证页尚未完成，未重复打开文章", "method": "browser"}
        if urlsplit(url).hostname == "mp.weixin.qq.com":
            raw = _read_article(browser, re.sub(r"^http:", "https:", url), 60000)
            return {"status": raw["status"], "content": raw.get("content", ""), "links": raw.get("links", []),
                    "url": raw.get("url", url), "published_at": raw.get("published_at", ""), "method": "browser",
                    "image_urls": raw.get("image_urls", []), "image_count": raw.get("image_count", 0),
                    "truncated": raw.get("truncated", False), "images_truncated": raw.get("images_truncated", False),
                    "verification": raw.get("verification"), "error": raw.get("error")}
        tab = browser.open(url)
        script = r"""(() => {const root=document.querySelector('main,[role=main]')||document.body;
          const content=root?.innerText?.trim()||'';return {url:location.href, content, ready:document.readyState==='complete',
          blocked:/captcha|antispider|verify/i.test(location.pathname)||(!document.querySelector('main')&&content.length<1500&&/验证码|环境异常|访问过于频繁/.test(content)),
          links:Array.from(root?.querySelectorAll('a[href]')||[]).slice(0,300).map(a=>({text:a.innerText.trim(),url:a.href})),
          published_at:document.querySelector('meta[property="article:published_time"]')?.content||''};})()"""
        data = browser.wait(tab, script, lambda value: value.get("blocked") or value.get("ready") and len(value.get("content", "")) > 250)
        if data.get("blocked"):
            state = browser.preserve_verification(tab, data.get("url") or url)
            return {"status": "blocked", "content": "", "links": [], "url": url, "verification": state,
                    "error": "页面要求手动验证，已保留Chrome标签页", "method": "browser"}
        return {**data, "content": data.get("content", "")[:60000], "truncated": len(data.get("content", "")) > 60000,
                "status": "ok" if data.get("content") else "unavailable", "method": "browser"}


async def read_article_images(page):
    """Read article images as evidence, preserving failures and explicit coverage limits."""
    urls = list(dict.fromkeys(page.get("image_urls", [])))
    if not urls:
        return page
    from ..config import get_ai_config
    from ..tools.document import _ocr
    from PIL import Image
    failures, texts = [], []
    try:
        get_ai_config("ocr", default_base_url="https://api.siliconflow.cn/v1", default_model="deepseek-ai/DeepSeek-OCR")
    except ValueError:
        return {**page, "image_read_state": "unavailable", "image_errors": ["图片 OCR 未配置，图片内容尚未读取"], "images_read": 0}
    def recognize(data):
        with Image.open(io.BytesIO(data)) as image:
            if image.width <= 32 and image.height <= 32:
                return ""  # Tracking pixels and tiny decorative icons do not contain a readable JD.
            if image.width * image.height > 35_000_000:
                raise ValueError("图片像素过大，未完成识别")
            image.load()
            image = image.convert("RGB")
            if image.width > 1600:
                image = image.resize((1600, max(1, round(image.height * 1600 / image.width))))
            if image.height > 2200 * 16:
                raise ValueError("长图超过16段识别上限，未完成识别")
            parts = []
            for top in range(0, image.height, 2200):
                buf = io.BytesIO()
                image.crop((0, top, image.width, min(image.height, top + 2200))).save(buf, format="PNG")
                parts.append(_ocr(buf.getvalue(), "image/png"))
            return "\n\n".join(parts)
    async with httpx.AsyncClient(timeout=30, trust_env=False, headers={"User-Agent": USER_AGENT}) as client:
        for index, url in enumerate(urls[:30], 1):
            try:
                for _ in range(6):
                    await validate_target(url)
                    async with client.stream("GET", url) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            continue
                        response.raise_for_status()
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > 8_000_000:
                                raise ValueError("图片超过8MB识别上限")
                        break
                else:
                    raise ValueError("图片重定向次数过多")
                content = await asyncio.to_thread(recognize, bytes(data))
                if content:
                    texts.append(f"图片{index}识别正文（需结合原图核对）：\n{content}")
            except (httpx.HTTPError, ValueError, OSError, Image.DecompressionBombError) as error:
                reason = str(error)[:160] if isinstance(error, ValueError) else type(error).__name__
                failures.append(f"图片{index}读取或OCR失败（{reason}），未把该图片视为已读")
    if len(urls) > 30 or page.get("images_truncated"):
        failures.append("文章图片超过本轮识别数量上限，仍有图片未读")
    joined = "\n\n".join(filter(None, [page.get("content", ""), *texts]))
    return {**page, "content": joined[:60000], "truncated": page.get("truncated", False) or len(joined) > 60000,
            "image_read_state": "partial" if failures else "complete", "image_errors": failures,
            "images_read": min(len(urls), 30) - sum("OCR失败" in value for value in failures)}


async def complete_page(page):
    page = await read_article_images(page)
    partial = page.get("truncated") or page.get("image_read_state") in {"partial", "unavailable"}
    return {**page, "status": "partial" if partial else "ok"}


async def extract_page(url, *, render=False):
    errors = []
    methods = ["direct_http"]
    if capabilities()["firecrawl"]:
        methods.append("firecrawl")
    if capabilities()["anysearch"]:
        methods.append("anysearch")
    for method in methods:
        try:
            data = await direct_extract(url) if method == "direct_http" else await provider_extract(url, method)
            if len(data["content"].strip()) < 100 and not data.get("image_urls"):
                raise ValueError("未读到足够正文，可能是动态页面")
            if method == "direct_http" and not data.get("image_urls") and not re.search(r"招聘|岗位|职位|实习|校招|任职|职责|career|vacanc|job", data["content"], re.I):
                raise ValueError("页面未出现招聘正文，可能需要渲染")
            return {**await complete_page(data), "errors": errors}
        except (httpx.HTTPError, ValueError, OSError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            errors.append({"method": method, "error": type(exc).__name__, "http_status": status,
                           "reason": str(exc) if isinstance(exc, ValueError) else f"请求失败，HTTP状态：{status or '连接或超时错误'}"})
    if render and os.getenv("RADAR_BROWSER_FALLBACK", "1") != "0":
        try:
            await validate_target(url)
            async with BROWSER_LOCK:
                task = asyncio.create_task(asyncio.to_thread(browser_extract, url))
                try:
                    rendered = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await asyncio.gather(task, return_exceptions=True)
                    raise
            if rendered["status"] == "blocked":
                return {**rendered, "errors": errors}
            if len(rendered.get("content", "")) >= 100 or rendered.get("image_urls"):
                return {**await complete_page(rendered), "errors": errors}
        except (httpx.HTTPError, ValueError, OSError, KeyError) as exc:
            errors.append({"method": "browser", "error": type(exc).__name__,
                           "reason": "浏览器正文读取通道未连接，请启动CDP代理并允许Chrome调试连接" if isinstance(exc, httpx.ConnectError)
                           else "浏览器未取得正文或等待超时"})
    return {"status": "unavailable", "content": "", "url": url, "links": [], "errors": errors,
            "error": "未取得有效正文；" + "；".join(dict.fromkeys(item.get("reason", "读取失败") for item in errors))}


JOB_WORDS = re.compile(r"招聘|校招|应届|毕业生|实习|管培|招录|职位|岗位|工程师|算法|研发|开发|career|job|opening", re.I)
NOISE = re.compile(r"常见问题|招聘流程|面试经验|攻略|公司介绍|企业文化|隐私|登录|注册")


def extract_jobs(page, site):
    candidates = [link for link in page.get("links", []) if JOB_WORDS.search(link["text"]) and not NOISE.search(link["text"]) and 4 <= len(link["text"]) <= 120]
    if not candidates:
        candidates = [{"text": line.strip(), "url": site["url"]} for line in page.get("content", "").splitlines()
                      if 6 <= len(line.strip()) <= 120 and JOB_WORDS.search(line) and not NOISE.search(line)]
    jobs = []
    for entry in candidates[:50]:
        job = normalize_job({"company": site["company"], "role": entry["text"], "url": entry["url"],
            "industry": site["industry"], "published_at": page.get("published_at"), "description": page.get("content", "")[:6000]},
            source_type="official_site", source_name="企业官网/固定公众号节点")
        if job:
            job.update(detail_state="read", fetched_at=datetime.now().astimezone().isoformat(), extraction_method=page.get("method"))
            jobs.append(job)
    return deduplicate(jobs)


def role_match_score(job, role):
    """Specific direction words must match; generic '开发/算法' alone cannot consume recall."""
    title = str(job.get("role", "")).casefold()
    role = str(role).casefold()
    if re.search(r"大模型.*应用|llm.*应用|rag|agent|智能体", role):
        # Agent/RAG are common names for LLM application roles. Conversely,
        # a generic foundation-model algorithm title does not establish this direction.
        application = re.findall(r"rag|agent|智能体|大模型应用|ai应用", title)
        if application:
            return 10 if len(title) < 70 else 5
        if not re.search(r"rag|agent|智能体|应用开发|应用工程", str(job.get("description", "")), re.I):
            return 0
        return 3
    terms = [term for term in re.split(r"[\s、/，,（）()]+", role) if term]
    score = sum(4 for term in terms if term in title)
    compact = re.sub(r"\s+", "", role)
    if len(compact) >= 3 and compact in re.sub(r"\s+", "", title):
        return max(score, 12)
    distinctive = re.findall(r"多模态|大模型|智能驾驶|计算机视觉|自然语言|强化学习|推荐|搜索|后端|服务端|前端|运营|产品|设计|测试|金融|财务|销售|agent|rag|vlm|llm|java|python", role, re.I)
    if distinctive:
        return max(score, sum(3 for term in distinctive if term in title)) if any(term in title for term in distinctive) else 0
    core = re.sub(r"工程师|实习生|研究员|专家|资深|高级|初级|开发|研发|算法|方向|岗位", "", compact)
    if len(core) >= 2:
        return max(score, 3) if core in title else 0
    return max(score, 2) if compact and compact in title else 0


def candidate_identity(job):
    return tuple(str(job.get(key, "")).strip() for key in ("company", "role", "city", "batch", "url"))


def match_score(job, roles=(), cities=(), companies=(), recruitment_types=(), query=""):
    haystack = " ".join(text(job.get(k)) for k in ("company", "role", "city", "batch", "industry")).casefold()
    score = max((role_match_score(job, role) for role in roles), default=0)
    if roles and score == 0:
        return 0
    if cities and not any(city in job["city"] for city in cities) and job["city"] and job["city"] not in {"多地", "全国"}:
        return 0
    if companies and not any(company.casefold() in job["company"].casefold() for company in companies):
        return 0
    if recruitment_types == ["实习"] and not re.search(r"实习", job["batch"] + job["role"]):
        return 0
    if cities and any(city in job["city"] for city in cities):
        score += 3
    if query and not roles:
        terms = [term for term in re.split(r"[\s、/，,]+", query.casefold()) if len(term) >= 2]
        score += sum(2 for term in terms if term in haystack)
        if not score:
            return 0
    return score or 1


async def search_jobs(intent, request, limit=30, read_limit=5, publish=None):
    async def radar_data():
        try:
            return await sync_jobs(publish=publish)
        except (httpx.HTTPError, OSError, ValueError):
            cached = read_jobs()
            cached["limitations"].append("Radar 同步未完成，本轮使用其缓存及 JobHunter 本地岗位。")
            return {**cached, "status": "partial"}
    data, market = await asyncio.gather(radar_data(), asyncio.to_thread(read_jobhunter_jobs))
    market_jobs = []
    for row in market["jobs"]:
        job = normalize_job(row, source_type="jobhunter", source_name=row["source_name"], snapshot_at=row["snapshot_at"])
        if job:
            job.update(source_record_id=row["source_record_id"], salary=row.get("salary", ""),
                       published_at_source=row["published_at_source"])
            market_jobs.append(job)
    radar_count = len(data["jobs"])
    combined = [*data["jobs"], *market_jobs]
    data["jobs"] = deduplicate(combined)
    data["limitations"] = list(dict.fromkeys([*data["limitations"], *market["limitations"]]))
    merge_stats = {"radar_records": radar_count, "jobhunter_records": len(market_jobs),
                   "merged_records": len(data["jobs"]), "duplicates_removed": len(combined) - len(data["jobs"]),
                   "jobhunter_status": market["status"]}
    if market["status"] == "unavailable":
        data["status"] = "partial"
    if publish:
        await publish("merge", title="合并 Radar 与 JobHunter 岗位", **merge_stats)
    roles = list(dict.fromkeys([*intent.get("roles", []), *intent.get("expanded_roles", [])]))
    excluded = {tuple(row) for row in intent.get("_excluded_records", []) if isinstance(row, (list, tuple)) and len(row) == 5}
    ranked, audits = [], []
    for job in data["jobs"]:
        if candidate_identity(job) in excluded:
            continue
        if intent.get("published_after") and publication_state(job.get("published_at"), published_after=intent["published_after"]) == "outside_window":
            continue
        score = match_score(job, roles, intent.get("cities", []), intent.get("companies", []), intent.get("recruitment_types", []), request)
        if score:
            ranked.append((score, job))
    ranked.sort(key=lambda pair: (not is_expired(pair[1]["deadline"]), pair[0], bool(pair[1].get("url") or pair[1].get("announcement_url")), pair[1].get("updated_at", "")), reverse=True)
    if intent.get("published_after"):
        ranked.sort(key=lambda pair: publication_state(pair[1].get("published_at"), published_after=intent["published_after"]) != "within_window")
    # Reserve coverage across each requested direction and city, rather than
    # allowing one broad direction or larger city's pool to consume the budget.
    cities = intent.get("cities", [])
    remaining, selected = [job for _, job in ranked], []
    directions = intent.get("roles", []) or [""]
    if len(cities) > 1 or len(directions) > 1:
        while remaining and len(selected) < limit:
            added = False
            for direction in directions:
                for city in cities or [""]:
                    job = next((row for row in remaining if (not city or city in row["city"])
                                and (not direction or role_match_score(row, direction))), None)
                    if job is not None and len(selected) < limit:
                        selected.append(dict(job))
                        remaining.remove(job)
                        added = True
            if not added:
                break
    selected.extend(dict(job) for job in remaining[:limit - len(selected)])
    if read_limit:
        await enrich_jobs(selected, read_limit=read_limit, publish=publish)
        if intent.get("published_after"):
            selected = [job for job in selected if publication_state(job.get("published_at"), published_after=intent["published_after"]) != "outside_window"]
    for index, job in enumerate(selected, 1):
        reason = "截止日期已过" if is_expired(job["deadline"]) else "招聘汇总线索，等待岗位语义核对"
        audit = {"page": 1, "rank": index, "title": f"{job['company']} · {job['role']}", "url": job["url"],
            "article_url": job.get("announcement_url"), "published_at": job.get("published_at"), "updated_at": job.get("updated_at"),
            "source_type": job["source_type"], "source_name": job["source_name"], "provenance": job.get("provenance", []),
            "status": "old" if is_expired(job["deadline"]) else "retained", "reason": reason,
            "read": job["detail_state"] == "read", "content_preview": job.get("description", "")[:1000]}
        audits.append(audit)
        if publish:
            await publish("candidate", query="Radar 与 JobHunter 合并岗位检索", **audit)
    return {"status": data["status"], "jobs": selected, "total_records": len(data["jobs"]), "matched_records": len(ranked),
        "candidates": audits, "limitations": data["limitations"], "mode": data["mode"], "fetched_at": data.get("fetched_at"),
        "merge_stats": merge_stats}


async def enrich_jobs(selected, read_limit=5, publish=None):
    """Spend detail reads on semantically selected jobs; try their official entry if an announcement fails."""
    semaphore = asyncio.Semaphore(3)
    pages = {}
    async def read_page(url, job):
        if publish:
            await publish("read", title=f"{job['company']} · {job['role']}", reason="读取官方公告或投递页面，补充核对岗位正文")
        async with semaphore:
            return await extract_page(url, render=True)
    async def read(job):
        urls = list(dict.fromkeys(url for url in (job.get("announcement_url"), job.get("url")) if url))
        if not urls:
            job["detail_state"] = "missing_url"
            return
        attempts, verification = [], None
        for url in urls:
            if url not in pages:
                pages[url] = asyncio.create_task(read_page(url, job))
            page = await pages[url]
            attempts.extend({**attempt, "url": url} for attempt in page.get("errors", []))
            if page.get("verification"):
                verification = page["verification"]
            if page["status"] in {"ok", "partial"}:
                break
            attempts.append({"url": url, "reason": page.get("error", "未取得正文")})
        job["detail_state"] = "read" if page["status"] == "ok" else "partial" if page["status"] == "partial" else "failed"
        job["detail_error"] = page.get("error") or "；".join(page.get("image_errors", [])) or ("原文超过正文读取上限" if page.get("truncated") else "")
        job["detail_attempts"] = attempts
        if verification and page["status"] not in {"ok", "partial"}:
            job["verification"] = verification
        if page["status"] in {"ok", "partial"}:
            job.update(description=page["content"], detail_url=page["url"], extraction_method=page["method"])
            job.update(content_truncated=bool(page.get("truncated")), image_read_state=page.get("image_read_state", "none"),
                       image_count=page.get("image_count", 0), images_read=page.get("images_read", 0))
            if page.get("published_at"):
                job["published_at"] = page["published_at"]
                job["published_at_source"] = "article_metadata"
        if publish:
            await publish("read_complete", title=f"{job['company']} · {job['role']}", detail_state=job["detail_state"],
                          published_at=job.get("published_at"), reason=job.get("detail_error") or "正文与图片读取完成")
    read_candidates, picked_urls = [], set()
    for job in selected:
        url = job.get("announcement_url") or job.get("url")
        if not url:
            job["detail_state"] = "missing_url"
        elif job.get("detail_state") == "read":
            continue
        elif url in picked_urls or len(picked_urls) < read_limit:
            picked_urls.add(url)
            read_candidates.append(job)
    tasks = [asyncio.create_task(read(job)) for job in read_candidates]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in [*tasks, *pages.values()]:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, *pages.values(), return_exceptions=True)
    return selected


async def crawl_sites(industry="", keyword="", limit=20, publish=None):
    sites = [site for site in catalog() if not industry or site["industry"] == industry]
    if keyword:
        matching = [site for site in sites if keyword.casefold() in (site["company"] + site["industry"]).casefold()]
        if matching:
            sites = matching
    sites = sites[:limit]
    queue = asyncio.Queue()
    for site in sites:
        queue.put_nowait(site)
    jobs, results = [], []
    async def worker():
        while not queue.empty():
            try:
                site = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            page = await extract_page(site["url"])
            extracted = extract_jobs(page, site) if page["status"] == "ok" else []
            if keyword:
                extracted = [job for job in extracted if keyword.casefold() in (job["company"] + job["role"] + job["city"]).casefold()]
            jobs.extend(extracted)
            item = {"company": site["company"], "url": site["url"], "status": page["status"], "count": len(extracted), "error": page.get("error")}
            results.append(item)
            if publish:
                await publish("crawl", **item, completed=len(results), total=len(sites))
    tasks = [asyncio.create_task(worker()) for _ in range(min(3, len(sites)))]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if jobs:
            async with WRITE_LOCK:
                previous = read_json(STATE / "crawled.json", {}).get("jobs", [])
                write_json(STATE / "crawled.json", {"jobs": deduplicate([*previous, *jobs])})
    return {"status": "ok" if jobs else "empty", "jobs": deduplicate(jobs), "sites": results, "count": len(deduplicate(jobs))}
