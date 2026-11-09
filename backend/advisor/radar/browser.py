"""Browser session and direct article reading for Radar sources; no search engine integration."""
import json
import os
import re
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from threading import Lock
from time import monotonic, sleep
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

import httpx



TIMEZONE = ZoneInfo("Asia/Shanghai")
# 仅缓存成功读取的公开文章；按浏览器服务隔离，最多64个链接别名，5分钟过期。
_ARTICLE_CACHE = OrderedDict()
_CACHE_LOCK = Lock()
_CACHE_TTL = 300
_CACHE_LIMIT = 64
_PENDING_VERIFICATIONS = {}
VERIFICATION_SCRIPT = r"""(() => ({url: location.href, blocked:
    /antispider|captcha|verify/i.test(location.pathname) ||
    (!document.querySelector('main, #js_content') && /验证码|访问过于频繁|环境异常|完成验证/.test(document.body?.innerText || ''))}))()"""
ARTICLE_SCRIPT = r"""(() => {
    const text = selector => document.querySelector(selector)?.innerText?.trim() || '';
    const meta = name => document.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.content || '';
    const root = document.querySelector('#js_content');
    const body = document.body?.innerText || '';
    const images = root ? Array.from(root.querySelectorAll('img')).map(img => {
        const src = img.getAttribute('data-src') || img.getAttribute('src');
        try { return src ? new URL(src, location.href).href : ''; } catch { return ''; }
    }) : [];
    const links = root ? Array.from(root.querySelectorAll('a[href]')).map(a => ({text: a.innerText.trim(), url: a.href})) : [];
    if (window.msg_source_url) links.push({text: '阅读原文', url: window.msg_source_url});
    const scriptTime = Array.from(document.scripts).map(s => s.textContent.match(/\b(?:ct|create_time)\s*[:=]\s*["']?(\d{10,13})/)).find(Boolean)?.[1] || '';
    return {url: location.href, canonical_url: document.querySelector('link[rel="canonical"]')?.href || window.msg_link || location.href,
        title: text('#activity-name') || meta('og:title'), account: text('#js_name') || text('.profile_nickname'),
        timestamp: String(window.ct || window.create_time || scriptTime || ''), published_label: text('#publish_time'),
        biz: String(window.biz || window.appuin || ''), mid: String(window.mid || window.appmsgid || ''),
        idx: String(window.idx || window.itemidx || ''),
        content: root?.innerText?.trim() || '', images, links, has_content: Boolean(root),
        blocked: /verify|captcha|antispider/i.test(location.pathname) || (!root && /环境异常|完成验证|访问过于频繁/.test(body)),
        deleted: /该内容已被发布者删除|此内容因违规无法查看|链接已过期/.test(body)};
})()"""


class _BrowserSession:
    def __enter__(self):
        self.client = httpx.Client(base_url=os.getenv("RADAR_BROWSER_PROXY_URL", os.getenv("WECHAT_BROWSER_PROXY_URL", "http://localhost:3456")),
                                   timeout=35, trust_env=False)
        self.tabs = set()
        return self

    def __exit__(self, *args):
        for tab in list(self.tabs):
            self.close(tab)
        self.client.close()

    def open(self, url: str) -> str:
        response = self.client.get("/new", params={"url": url})
        response.raise_for_status()
        tab = response.json()["targetId"]
        self.tabs.add(tab)
        return tab

    def evaluate(self, tab: str, expression: str):
        response = self.client.post("/eval", params={"target": tab}, content=expression.encode("utf-8"))
        response.raise_for_status()
        data = response.json()
        if "value" not in data:
            raise ValueError("浏览器未返回可读取的页面数据")
        return data["value"]

    def preserve_verification(self, tab: str, url: str):
        self.tabs.discard(tab)  # Hand this tab to the user instead of closing it.
        state = {"url": url, "target_id": tab, "message": "验证页已保留在Chrome中，请手动完成验证后重新搜索。"}
        with _CACHE_LOCK:
            _PENDING_VERIFICATIONS[str(self.client.base_url)] = state
        return state

    def pending_verification(self):
        key = str(self.client.base_url)
        with _CACHE_LOCK:
            state = _PENDING_VERIFICATIONS.get(key)
        if state is None:
            return None
        try:
            current = self.evaluate(state["target_id"], VERIFICATION_SCRIPT)
            if current.get("blocked"):
                return {**state, "url": current.get("url") or state["url"]}
        except (httpx.HTTPError, ValueError):
            pass
        with _CACHE_LOCK:
            _PENDING_VERIFICATIONS.pop(key, None)
        return None

    def wait(self, tab: str, script: str, ready) -> dict:
        end = monotonic() + 12
        data = {}
        while monotonic() < end:
            try:
                data = self.evaluate(tab, script)
                if isinstance(data, dict) and ready(data):
                    return data
            except (httpx.HTTPStatusError, ValueError):
                pass  # 导航时执行上下文可能重建；不将过渡页面当作搜索结果。
            sleep(0.3)
        return data if isinstance(data, dict) else {}

    def close(self, tab: str):
        try:
            self.client.get("/close", params={"target": tab}).raise_for_status()
        except httpx.HTTPError:
            pass
        self.tabs.discard(tab)


def _article_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (parsed.scheme == "https" and parsed.hostname == "mp.weixin.qq.com"
                and parsed.port in (None, 443) and not parsed.username and not parsed.password
                and (parsed.path == "/s" or parsed.path.startswith("/s/")))
    except ValueError:
        return False


def _publication(timestamp: str, label: str) -> str | None:
    try:
        if timestamp.isdigit():
            seconds = int(timestamp) / (1000 if len(timestamp) == 13 else 1)
            return datetime.fromtimestamp(seconds, TIMEZONE).isoformat()
        match = re.search(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?(?:\s+(\d{1,2}):(\d{2}))?", label)
        if match:
            year, month, day, hour, minute = match.groups()
            return datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=TIMEZONE).isoformat()
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _article_key(url: str) -> str:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if all(key in query for key in ("__biz", "mid", "idx")):
        return urlencode({key: query[key][0] for key in ("__biz", "mid", "idx")})
    return parsed.path if parsed.path.startswith("/s/") else url


def _cache_key(url: str) -> tuple[str, str]:
    return os.getenv("RADAR_BROWSER_PROXY_URL", os.getenv("WECHAT_BROWSER_PROXY_URL", "http://localhost:3456")), _article_key(url)


def _cached_article(url: str) -> dict | None:
    with _CACHE_LOCK:
        key = _cache_key(url)
        cached = _ARTICLE_CACHE.get(key)
        if cached is None:
            return None
        if monotonic() >= cached[0]:
            del _ARTICLE_CACHE[key]
            return None
        _ARTICLE_CACHE.move_to_end(key)
        return cached[1]


def _cache_article(article: dict) -> None:
    with _CACHE_LOCK:
        for url in {article["requested_url"], article["url"]}:
            key = _cache_key(url)
            _ARTICLE_CACHE[key] = (monotonic() + _CACHE_TTL, article)
            _ARTICLE_CACHE.move_to_end(key)
        while len(_ARTICLE_CACHE) > _CACHE_LIMIT:
            _ARTICLE_CACHE.popitem(last=False)


def _article_excerpt(article: dict, url: str, max_chars: int) -> dict:
    result = deepcopy(article)
    content = result["content"]
    result.update(requested_url=url, content=content[:max_chars],
                  truncated=result["truncated"] or len(content) > max_chars)
    return result


def _read_article(browser: _BrowserSession, url: str, max_chars: int) -> dict:
    if not _article_url(url):
        return {"status": "invalid_url", "url": url, "error": "仅接受公开公众号文章的原文链接"}
    cached = _cached_article(url)
    if cached is not None:
        return _article_excerpt(cached, url, max_chars)
    tab = browser.open(url)
    try:
        raw = browser.wait(tab, ARTICLE_SCRIPT, lambda value: value.get("blocked") or value.get("deleted") or value.get("has_content"))
        if raw.get("blocked"):
            verification = browser.preserve_verification(tab, raw.get("url") or url)
            return {"status": "blocked", "url": url, "error": "原文要求浏览器验证，未读取到正文", "verification": verification}
        resolved = raw.get("url", "")
        if raw.get("deleted") or not _article_url(resolved) or not raw.get("has_content"):
            return {"status": "unavailable", "url": url, "error": "原文不可访问、已删除或链接已过期"}
        canonical = raw.get("canonical_url", "")
        article_url = canonical if _article_url(canonical) else resolved
        content = raw.get("content", "")
        images = list(dict.fromkeys(value for value in raw.get("images", []) if value.startswith(("https://", "http://"))))
        links = [item for item in raw.get("links", []) if item["url"].startswith(("https://", "http://"))]
        for value in re.findall(r"https?://[^\s<>\"']+", content):
            links.append({"text": "正文中的网址", "url": value.rstrip("，。；）】")})
        links = list({item["url"]: item for item in links}.values())
        published_at = _publication(raw.get("timestamp", ""), raw.get("published_label", ""))
        temporary = "signature" in parse_qs(urlsplit(article_url).query)
        article_id = ":".join(raw[key] for key in ("biz", "mid", "idx")) if all(raw.get(key) for key in ("biz", "mid", "idx")) else None
        article = {
            "status": "ok" if content else "image_only" if images else "unavailable",
            "url": article_url, "requested_url": url, "url_is_temporary": temporary,
            "article_id": article_id,
            "title": raw.get("title", ""), "account": raw.get("account", ""),
            "published_at": published_at, "published_at_source": "article_metadata" if published_at else "unknown",
            "content": content[:60000], "truncated": len(content) > 60000,
            "image_urls": images[:30], "image_count": len(images),
            "images_truncated": len(images) > 30, "links": links[:50], "links_truncated": len(links) > 50,
            "recruitment_status": "unknown", "publisher_verified": False,
            "limitations": ["未进行图片 OCR；图片中可能包含岗位、截止时间或二维码。"] if images else [],
        }
        if article["status"] in {"ok", "image_only"}:
            _cache_article(article)
        return _article_excerpt(article, url, max_chars)
    finally:
        if tab in browser.tabs:
            browser.close(tab)
