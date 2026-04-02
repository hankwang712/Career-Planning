#!/usr/bin/env python3
"""
Lightweight career news bridge for the Flask dashboard.

This keeps only the "daily snapshot + multi-source aggregation" approach from
the previous standalone news module and exposes a Python-first payload that
can be rendered directly by the existing web app without importing another
frontend structure.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")
CAREER_NEWS_CACHE_FILE = os.path.join(APP_DATA_DIR, "career_news_snapshot.json")
CAREER_NEWS_LOCK = threading.Lock()

CAREER_NEWS_TIMEZONE = ZoneInfo("Asia/Shanghai")
CAREER_NEWS_REFRESH_HOUR = 12
CAREER_NEWS_DISPLAY_LIMIT = 9
CAREER_NEWS_FETCH_LIMIT = 180
CAREER_NEWS_MAX_ITEMS = 50
CAREER_NEWS_TIMEOUT_SECONDS = 8
CAREER_NEWS_EMPTY_RETRY_MINUTES = 20
CAREER_NEWS_MAX_AGE_DAYS = 45
CAREER_NEWS_DIRECT_MIN_TECH_HITS = 2
CAREER_NEWS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

CAREER_NEWS_KEYWORDS = [
    "职业规划",
    "职业发展",
    "就业",
    "工作",
    "求职",
    "校招",
    "秋招",
    "春招",
    "实习",
    "面试",
    "简历",
    "招聘",
    "岗位",
    "职场",
    "毕业生",
    "技能提升",
    "转行",
    "薪资",
    "裁员",
    "扩招",
    "远程办公",
    "career",
    "careers",
    "job",
    "jobs",
    "hiring",
    "hire",
    "intern",
    "internship",
    "employment",
    "future of work",
    "workforce",
    "recruit",
    "recruiting",
    "layoff",
    "layoffs",
    "salary",
    "resume",
    "upskill",
    "reskill",
    "employee",
    "employees",
    "worker",
    "workers",
    "unemployment",
    "labor",
    "labour",
    "workplace",
    "失业",
    "员工",
    "就业市场",
    "招聘市场",
]

TECH_NEWS_KEYWORDS = [
    "计算机",
    "互联网",
    "科技行业",
    "程序员",
    "软件工程师",
    "开发者",
    "开发工程师",
    "前端",
    "后端",
    "全栈",
    "测试工程师",
    "算法工程师",
    "ai工程师",
    "大模型",
    "人工智能",
    "机器学习",
    "数据分析",
    "数据科学",
    "云计算",
    "网络安全",
    "产品经理",
    "数字化",
    "developer",
    "developers",
    "software",
    "engineer",
    "engineering",
    "programmer",
    "frontend",
    "backend",
    "full stack",
    "machine learning",
    "artificial intelligence",
    "data engineer",
    "data scientist",
    "cybersecurity",
    "cloud",
    "product manager",
    "ai",
    "agent",
    "agents",
    "智能体",
    "llm",
    "llms",
    "model",
    "models",
    "openai",
    "claude",
    "copilot",
    "code",
    "coding",
    "open source",
    "开源",
    "database",
    "node.js",
    "startup",
    "ipo",
    "chip",
    "chips",
    "semiconductor",
    "robotics",
    "data center",
    "datacenter",
    "数据中心",
]

IRRELEVANT_KEYWORDS = [
    "足球",
    "nba",
    "cba",
    "篮球",
    "网球",
    "羽毛球",
    "乒乓球",
    "运动员",
    "退役",
    "休赛期",
    "俱乐部",
    "娱乐圈",
    "明星",
    "综艺",
    "电影票房",
    "彩票",
    "培训机构",
    "哪家好",
    "口碑好的",
    "招生",
    "学费",
    "课程推荐",
    "报班",
]

ATOM_NAMESPACE = "{http://www.w3.org/2005/Atom}"
TECH_PRIORITY_TOPICS = {"程序员就业", "AI 与计算机岗位", "科技行业变化"}
TECH_PRIORITY_BONUS = 4


def _build_google_news_search_feed(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote_plus(query)
        + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    )


CAREER_NEWS_RSS_SOURCES = [
    {
        "kind": "search",
        "source": "Google News",
        "topic": "职业规划",
        "url": _build_google_news_search_feed(
            "职业规划 OR 职业发展 OR 职场技能 OR 就业趋势 求职 岗位 -体育 -篮球 -足球 -网球 -退役"
        ),
    },
    {
        "kind": "search",
        "source": "Google News",
        "topic": "求职就业",
        "url": _build_google_news_search_feed(
            "大学生 就业 OR 校招 OR 春招 OR 秋招 OR 实习 OR 面试 -培训 -招生 -学费"
        ),
    },
    {
        "kind": "search",
        "source": "Google News",
        "topic": "程序员就业",
        "url": _build_google_news_search_feed(
            "程序员 OR 软件工程师 OR 开发者 招聘 OR 就业 OR 技能提升 -培训 -课程 -招生"
        ),
    },
    {
        "kind": "search",
        "source": "Google News",
        "topic": "AI 与计算机岗位",
        "url": _build_google_news_search_feed(
            "AI 工程师 OR 大模型 OR 数据分析师 招聘 OR 岗位 OR 薪资 -培训 -课程 -口碑"
        ),
    },
    {
        "kind": "search",
        "source": "Google News",
        "topic": "科技行业变化",
        "url": _build_google_news_search_feed(
            "科技行业 裁员 OR 扩招 OR 招聘 OR 远程办公 OR 技术人才"
        ),
    },
    {
        "kind": "direct",
        "source": "InfoQ",
        "topic": "技术趋势",
        "url": "https://www.infoq.cn/feed",
    },
    {
        "kind": "direct",
        "source": "IT之家",
        "topic": "科技行业",
        "url": "https://www.ithome.com/rss/",
    },
    {
        "kind": "direct",
        "source": "TechCrunch",
        "topic": "全球科技",
        "url": "https://techcrunch.com/feed/",
    },
    {
        "kind": "direct",
        "source": "Wired",
        "topic": "AI 与工作",
        "url": "https://www.wired.com/feed/rss",
    },
    {
        "kind": "direct",
        "source": "Ars Technica",
        "topic": "开发与行业",
        "url": "https://feeds.arstechnica.com/arstechnica/index/",
    },
    {
        "kind": "direct",
        "source": "The Verge",
        "topic": "科技职场",
        "url": "https://www.theverge.com/rss/index.xml",
    },
]


def _snapshot_window(now: datetime | None = None) -> dict:
    current = now.astimezone(CAREER_NEWS_TIMEZONE) if now else datetime.now(CAREER_NEWS_TIMEZONE)
    release_at = current.replace(
        hour=CAREER_NEWS_REFRESH_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if current < release_at:
        release_at -= timedelta(days=1)
    next_refresh_at = release_at + timedelta(days=1)
    return {
        "snapshot_key": release_at.strftime("%Y-%m-%d"),
        "release_at": release_at,
        "next_refresh_at": next_refresh_at,
    }


def _ensure_storage() -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)


def _read_cached_snapshot() -> dict | None:
    try:
        with open(CAREER_NEWS_CACHE_FILE, "r", encoding="utf-8") as fp:
            payload = json.load(fp)
        return payload if isinstance(payload, dict) else None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _write_cached_snapshot(payload: dict) -> None:
    _ensure_storage()
    temp_path = f"{CAREER_NEWS_CACHE_FILE}.tmp"
    with open(temp_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    os.replace(temp_path, CAREER_NEWS_CACHE_FILE)


def _clean_text(value: str | None) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_text(value: str | None) -> str:
    return _clean_text(value).lower()


def _truncate(text: str, limit: int = 96) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}…"


def _parse_pub_date(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CAREER_NEWS_TIMEZONE)
        return parsed.astimezone(CAREER_NEWS_TIMEZONE)
    except (TypeError, ValueError, IndexError, OverflowError):
        pass
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CAREER_NEWS_TIMEZONE)
        return parsed.astimezone(CAREER_NEWS_TIMEZONE)
    except ValueError:
        return None


def _collect_hits(text: str, keywords: list[str]) -> list[str]:
    hits = []
    for keyword in keywords:
        normalized = keyword.lower()
        if normalized and normalized in text and normalized not in hits:
            hits.append(normalized)
    return hits


def _score_relevance(source: dict, title: str, summary: str) -> dict:
    haystack = _normalize_text(f"{title} {summary}")
    career_hits = _collect_hits(haystack, CAREER_NEWS_KEYWORDS)
    tech_hits = _collect_hits(haystack, TECH_NEWS_KEYWORDS)
    blocked_hits = _collect_hits(haystack, IRRELEVANT_KEYWORDS)

    score = len(career_hits) * 2 + len(tech_hits)
    if source.get("kind") == "search":
        score += 1

    if blocked_hits and score < 4:
        return {"accepted": False, "score": score, "labels": []}

    if source.get("kind") == "direct":
        accepted = (
            (bool(career_hits) and bool(tech_hits))
            or len(tech_hits) >= CAREER_NEWS_DIRECT_MIN_TECH_HITS
        )
    else:
        accepted = bool(career_hits) and score >= 3

    labels = []
    if career_hits:
        labels.append("career")
    if tech_hits:
        labels.append("tech")
    return {"accepted": accepted, "score": score, "labels": labels}


def _fetch_rss_xml(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": CAREER_NEWS_USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=CAREER_NEWS_TIMEOUT_SECONDS) as response:
        return response.read()


def _extract_atom_link(node: ET.Element) -> str:
    for link in node.findall(f"{ATOM_NAMESPACE}link"):
        href = _clean_text(link.attrib.get("href"))
        rel = (link.attrib.get("rel") or "alternate").strip().lower()
        if href and rel in {"alternate", ""}:
            return href
    for link in node.findall(f"{ATOM_NAMESPACE}link"):
        href = _clean_text(link.attrib.get("href"))
        if href:
            return href
    return ""


def _parse_feed_items(source: dict) -> tuple[list[dict], int]:
    xml_bytes = _fetch_rss_xml(source["url"])
    root = ET.fromstring(xml_bytes)

    rss_nodes = root.findall(".//item")
    if rss_nodes:
        nodes = rss_nodes
        parser_kind = "rss"
    else:
        nodes = root.findall(f".//{ATOM_NAMESPACE}entry")
        parser_kind = "atom"

    items = []
    for node in nodes:
        if parser_kind == "rss":
            title = _clean_text(node.findtext("title"))
            url = _clean_text(node.findtext("link"))
            summary = _truncate(
                node.findtext("description")
                or node.findtext("content")
                or node.findtext("summary")
            )
            published_raw = (
                node.findtext("pubDate")
                or node.findtext("published")
                or node.findtext("updated")
            )
        else:
            title = _clean_text(node.findtext(f"{ATOM_NAMESPACE}title"))
            url = _extract_atom_link(node)
            summary = _truncate(
                node.findtext(f"{ATOM_NAMESPACE}summary")
                or node.findtext(f"{ATOM_NAMESPACE}content")
            )
            published_raw = (
                node.findtext(f"{ATOM_NAMESPACE}published")
                or node.findtext(f"{ATOM_NAMESPACE}updated")
            )

        published_at = _parse_pub_date(published_raw)
        if not title or not url:
            continue
        if published_at and published_at < datetime.now(CAREER_NEWS_TIMEZONE) - timedelta(days=CAREER_NEWS_MAX_AGE_DAYS):
            continue

        relevance = _score_relevance(source, title, summary)
        if not relevance["accepted"]:
            continue

        items.append(
            {
                "title": title,
                "url": url,
                "summary": summary,
                "source": f"{source['source']} / {source['topic']}",
                "published_at": published_at.isoformat() if published_at else "",
                "published_label": published_at.strftime("%m-%d %H:%M") if published_at else "刚刚同步",
                "topic": source["topic"],
                "relevance_score": relevance["score"],
                "match_tags": relevance["labels"],
                "rank_score": (
                    relevance["score"]
                    + (TECH_PRIORITY_BONUS if source["topic"] in TECH_PRIORITY_TOPICS else 0)
                ),
                "_published_sort": published_at.timestamp() if published_at else 0,
            }
        )
    return items, len(nodes)


def _normalize_title_key(title: str) -> str:
    title_key = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    return re.sub(r"\s[-|｜丨]\s[^-|｜丨]+$", "", title_key)


def _dedupe_key(item: dict) -> str:
    title_key = _normalize_title_key(str(item.get("title") or ""))
    url_key = str(item.get("url") or "").strip().lower()
    if "news.google.com" in url_key:
        return title_key or url_key
    return url_key or title_key


def _dedupe_and_rank(items: list[dict], limit: int = CAREER_NEWS_FETCH_LIMIT) -> list[dict]:
    ranked = []
    seen = set()
    sorted_items = sorted(
        items,
        key=lambda item: (item.get("rank_score", 0), item.get("_published_sort", 0)),
        reverse=True,
    )
    for item in sorted_items:
        key = _dedupe_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        clean_item = dict(item)
        clean_item.pop("_published_sort", None)
        clean_item.pop("rank_score", None)
        ranked.append(clean_item)
        if len(ranked) >= limit:
            break
    return ranked


def _clean_cached_item(item: dict) -> dict:
    clean_item = dict(item)
    clean_item.pop("_published_sort", None)
    clean_item.pop("rank_score", None)
    return clean_item


def _item_timestamp(item: dict) -> float:
    dt = _parse_pub_date(item.get("published_at"))
    return dt.timestamp() if dt else 0.0


def _item_sort_key(item: dict) -> tuple[float, float, str]:
    return (
        _item_timestamp(item),
        float(item.get("relevance_score") or 0),
        _normalize_text(item.get("title") or ""),
    )


def _merge_and_trim_items(
    fetched_items: list[dict],
    cached_items: list[dict],
    max_items: int = CAREER_NEWS_MAX_ITEMS,
) -> list[dict]:
    merged_by_key = {}
    for item in list(fetched_items or []) + list(cached_items or []):
        if not isinstance(item, dict):
            continue
        key = _dedupe_key(item)
        if not key:
            continue
        candidate = _clean_cached_item(item)
        existing = merged_by_key.get(key)
        if existing is None or _item_sort_key(candidate) > _item_sort_key(existing):
            merged_by_key[key] = candidate

    merged_items = list(merged_by_key.values())
    merged_items.sort(key=_item_sort_key, reverse=True)
    if max_items > 0:
        merged_items = merged_items[:max_items]
    return merged_items


def _sort_and_trim_items_by_time(items: list[dict], max_items: int = CAREER_NEWS_MAX_ITEMS) -> list[dict]:
    if not isinstance(items, list):
        return []
    normalized = [_clean_cached_item(item) for item in items if isinstance(item, dict)]
    if not normalized:
        return []
    normalized.sort(key=_item_sort_key, reverse=True)
    if max_items > 0:
        normalized = normalized[:max_items]
    return normalized


def _stringify_fetch_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, URLError):
        reason = getattr(exc, "reason", exc)
        return str(reason)
    return str(exc) or exc.__class__.__name__


def _fetch_latest_career_news() -> tuple[list[dict], list[dict]]:
    items = []
    source_stats = []

    for source in CAREER_NEWS_RSS_SOURCES:
        stat = {
            "source": source["source"],
            "topic": source["topic"],
            "kind": source["kind"],
            "status": "ok",
            "raw_count": 0,
            "kept_count": 0,
            "error": "",
        }
        try:
            parsed_items, raw_count = _parse_feed_items(source)
            stat["raw_count"] = raw_count
            stat["kept_count"] = len(parsed_items)
            stat["status"] = "ok" if parsed_items else "empty"
            items.extend(parsed_items)
        except Exception as exc:
            stat["status"] = "error"
            stat["error"] = _stringify_fetch_error(exc)
        source_stats.append(stat)

    return _dedupe_and_rank(items), source_stats


def _build_empty_reason(source_stats: list[dict]) -> str:
    if not source_stats:
        return "当前还没有可用的新闻源。"

    error_stats = [stat for stat in source_stats if stat.get("status") == "error"]
    kept_stats = [stat for stat in source_stats if stat.get("kept_count", 0) > 0]

    if kept_stats:
        return ""

    if error_stats and len(error_stats) == len(source_stats):
        joined_errors = "；".join(
            filter(None, [str(stat.get("error") or "").strip() for stat in error_stats[:2]])
        )
        if "10013" in joined_errors or "访问权限" in joined_errors:
            return "当前环境禁止访问外部新闻源，所以没有抓到内容。"
        return "所有新闻源都抓取失败，通常是网络、代理或目标站点限制导致的。"

    if error_stats:
        return "部分新闻源抓取失败，其余源当前也没有命中职业/计算机行业相关文章。"

    return "新闻源可以访问，但当前查询词命中为空，或被职业/计算机行业过滤条件排除了。"


def _payload_base(window: dict) -> dict:
    return {
        "window_snapshot_key": window["snapshot_key"],
        "window_snapshot_label": window["release_at"].strftime("%Y-%m-%d %H:%M"),
        "next_refresh_label": window["next_refresh_at"].strftime("%Y-%m-%d %H:%M"),
        "refresh_rule": f"每日 {CAREER_NEWS_REFRESH_HOUR:02d}:00 更新",
    }


def _parse_generated_at(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=CAREER_NEWS_TIMEZONE)
    except ValueError:
        return None


def _should_reuse_cached_snapshot(
    cached: dict | None,
    window: dict,
    force_refresh: bool,
) -> bool:
    if force_refresh or not cached:
        return False

    window_key = str(cached.get("window_snapshot_key") or cached.get("snapshot_key") or "")
    if window_key != window["snapshot_key"]:
        return False

    items = cached.get("items") if isinstance(cached.get("items"), list) else []
    status = str(cached.get("status") or "")

    if items and status in {"ready", "partial"}:
        return True

    generated_at = _parse_generated_at(cached.get("generated_at"))
    if not generated_at:
        return False

    age = datetime.now(CAREER_NEWS_TIMEZONE) - generated_at
    if age < timedelta(minutes=CAREER_NEWS_EMPTY_RETRY_MINUTES):
        return status in {"empty", "error", "stale"} or bool(items)
    return False


def _build_ready_payload(
    window: dict,
    items: list[dict],
    source_stats: list[dict],
    previous_items: list[dict] | None = None,
) -> dict:
    generated_at = datetime.now(CAREER_NEWS_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    has_errors = any(stat.get("status") == "error" for stat in source_stats)
    cleaned_items = _merge_and_trim_items(items, previous_items or [])
    payload = {
        **_payload_base(window),
        "snapshot_key": window["snapshot_key"],
        "snapshot_label": window["release_at"].strftime("%Y-%m-%d %H:%M"),
        "generated_at": generated_at,
        "items": cleaned_items,
        "status": "partial" if has_errors else "ready",
        "is_stale": False,
        "empty_reason": "",
        "stale_reason": "",
        "source_stats": source_stats,
    }
    _write_cached_snapshot(payload)
    return payload


def _build_stale_payload(window: dict, cached: dict, source_stats: list[dict]) -> dict:
    generated_at = datetime.now(CAREER_NEWS_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    snapshot_label = str(cached.get("snapshot_label") or cached.get("window_snapshot_label") or "--")
    cleaned_items = _sort_and_trim_items_by_time(list(cached.get("items") or []))
    payload = {
        **_payload_base(window),
        "snapshot_key": str(cached.get("snapshot_key") or ""),
        "snapshot_label": snapshot_label,
        "generated_at": generated_at,
        "items": cleaned_items,
        "status": "stale",
        "is_stale": True,
        "empty_reason": _build_empty_reason(source_stats),
        "stale_reason": (
            f"今日 {window['release_at'].strftime('%Y-%m-%d %H:%M')} 刷新失败，"
            f"当前继续沿用 {snapshot_label} 的内容。"
        ),
        "source_stats": source_stats,
    }
    _write_cached_snapshot(payload)
    return payload


def _build_empty_payload(window: dict, source_stats: list[dict]) -> dict:
    generated_at = datetime.now(CAREER_NEWS_TIMEZONE).strftime("%Y-%m-%d %H:%M")
    has_errors = any(stat.get("status") == "error" for stat in source_stats)
    payload = {
        **_payload_base(window),
        "snapshot_key": window["snapshot_key"],
        "snapshot_label": window["release_at"].strftime("%Y-%m-%d %H:%M"),
        "generated_at": generated_at,
        "items": [],
        "status": "error" if has_errors else "empty",
        "is_stale": False,
        "empty_reason": _build_empty_reason(source_stats),
        "stale_reason": "",
        "source_stats": source_stats,
    }
    _write_cached_snapshot(payload)
    return payload


def _split_visible_items(items: list[dict], display_limit: int) -> tuple[list[dict], list[dict]]:
    ordered_items = _sort_and_trim_items_by_time(items, max_items=0)
    limit = max(0, int(display_limit or 0))
    if limit == 0:
        return [], ordered_items
    return ordered_items[:limit], ordered_items[limit:]


def _split_source_label(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if " / " in raw:
        left, right = raw.split(" / ", 1)
        return left.strip(), right.strip()
    return raw, ""


def _extract_domain_label(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(str(url or "").strip())
    except Exception:
        return ""
    host = (parsed.netloc or "").strip().lower()
    host = re.sub(r"^www\.", "", host)
    host = re.sub(r"^m\.", "", host)
    return host


def _build_preview_image(url: str) -> str:
    safe_url = str(url or "").strip()
    if not safe_url:
        return ""
    domain = _extract_domain_label(safe_url)
    if not domain or "news.google.com" in domain:
        return ""
    encoded = urllib.parse.quote(safe_url, safe="")
    return f"https://s.wordpress.com/mshots/v1/{encoded}?w=1200"


def _normalize_news_summary(summary: str, source_name: str, topic_label: str) -> str:
    text = _clean_text(summary)
    if text in {"点击查看原文", "点击查看原文>", "点击查看原文 >", "查看原文"}:
        text = ""
    if text:
        return text
    if source_name and topic_label:
        return f"{source_name} · {topic_label} 快讯，点击查看原文获取完整内容。"
    if source_name:
        return f"{source_name} 快讯，点击查看原文获取完整内容。"
    return ""


def _decorate_news_item(item: dict) -> dict:
    enriched = dict(item or {})
    source_name, source_topic = _split_source_label(str(enriched.get("source") or ""))
    topic_label = str(enriched.get("topic") or source_topic or "").strip()
    domain_label = _extract_domain_label(str(enriched.get("url") or ""))
    enriched["source_name"] = source_name or str(enriched.get("source") or "").strip()
    enriched["topic_label"] = topic_label
    enriched["domain_label"] = domain_label
    enriched["preview_image"] = _build_preview_image(str(enriched.get("url") or ""))
    enriched["summary"] = _normalize_news_summary(
        str(enriched.get("summary") or ""),
        enriched["source_name"],
        topic_label,
    )
    return enriched


def get_career_news_payload(
    force_refresh: bool = False,
    display_limit: int = CAREER_NEWS_DISPLAY_LIMIT,
) -> dict:
    window = _snapshot_window()

    with CAREER_NEWS_LOCK:
        cached = _read_cached_snapshot()
        cached_items = list(cached.get("items") or []) if cached and isinstance(cached.get("items"), list) else []
        if _should_reuse_cached_snapshot(cached, window, force_refresh):
            payload = dict(cached)
        else:
            items, source_stats = _fetch_latest_career_news()
            if items:
                payload = _build_ready_payload(window, items, source_stats, cached_items)
            elif cached and isinstance(cached.get("items"), list) and cached.get("items"):
                payload = _build_stale_payload(window, cached, source_stats)
            else:
                payload = _build_empty_payload(window, source_stats)

        # 动态清理：总量最多 50 条，按发布时间倒序保留最新内容。
        current_items = payload.get("items") if isinstance(payload.get("items"), list) else []
        trimmed_items = _sort_and_trim_items_by_time(current_items, max_items=CAREER_NEWS_MAX_ITEMS)
        if trimmed_items != current_items:
            payload["items"] = trimmed_items
            _write_cached_snapshot(payload)

    items = [
        _decorate_news_item(item)
        for item in _sort_and_trim_items_by_time(payload.get("items") if isinstance(payload.get("items"), list) else [])
    ]
    visible_items, hidden_items = _split_visible_items(items, display_limit)

    payload["items"] = items
    payload["visible_items"] = visible_items
    payload["hidden_items"] = hidden_items
    payload["display_limit"] = display_limit
    payload["total"] = len(items)
    payload["has_more"] = len(hidden_items) > 0
    return payload
