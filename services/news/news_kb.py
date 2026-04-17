"""
News Storage & RAG Module

存储层：所有新闻条目存入单个 JSON 文件（news_store.json），
        每条记录仅保存 title / content / published_at / source / url / summary。
        存储时 **不做 embedding**。

行业/趋势总览：职业报告中的行业分析使用 **近期新闻摘要归纳**（get_recent_news_context），
        按时间选取条目并做正文节选与 Markdown 拼装，**不走向量 RAG**。

RAG 层（按需）：当用户画像查询与新闻块在向量上足够接近时再检索——见
        get_profile_aligned_news_rag_context() 与 search_news_for_agent()：
        1. 读取 news_store.json
        2. 将每篇文章拼合后按 500 token / overlap=50 分块
        3. 对每个 chunk 做 embedding（结果缓存到 news_chunks_cache.json）
        4. 对 query 做 embedding，余弦相似度排序
        5. 返回达到 score 阈值的 top_k 相关 chunk
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# 路径 & 常量
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")

NEWS_STORE_FILE = os.path.join(APP_DATA_DIR, "news_store.json")
NEWS_CHUNKS_CACHE_FILE = os.path.join(APP_DATA_DIR, "news_chunks_cache.json")
NEWS_STORE_LOCK = threading.RLock()  # load 时可能就地修复并回写，需可重入

EMBEDDING_MODEL = "baai/bge-m3"
EMBEDDING_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_API_KEY = "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"

NEWS_MAX_ENTRIES = 500     # 最多保留条数
NEWS_MAX_AGE_DAYS = 45     # 超过此天数的条目会被裁剪
ARTICLE_FETCH_TIMEOUT = 8  # 抓取正文的超时（秒）
ARTICLE_CONTENT_MAX_CHARS = 12000  # 存入 news_store 的正文上限（提取干净后再截断）
ARTICLE_SUMMARY_MAX_CHARS = 220

_PLACEHOLDER_SUMMARY_KEYS = {
    "\u70b9\u51fb\u67e5\u770b\u539f\u6587",
    "\u70b9\u51fb\u67e5\u770b\u539f\u6587>",
    "\u70b9\u51fb\u67e5\u770b\u539f\u6587 >",
    "\u67e5\u770b\u539f\u6587",
    "readmore",
    "readmore>",
    "readmore>>",
    "vieworiginal",
    "vieworiginal>",
}


def _summary_key(text: str) -> str:
    cleaned = _sanitize_stored_text(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"[\s>＞:：|｜-]+", "", cleaned)
    return cleaned.lower()


def _is_placeholder_summary(text: str) -> bool:
    return _summary_key(text) in _PLACEHOLDER_SUMMARY_KEYS


def _build_summary_from_content(text: str, limit: int = ARTICLE_SUMMARY_MAX_CHARS) -> str:
    clean = _sanitize_stored_text(text)
    if not clean:
        return ""
    clean = re.sub(r"(?:\u67e5\u770b(?:\u82f1\u6587)?\u539f\u6587|read more|view original).*$", "", clean, flags=re.I)
    clean = re.sub(r"\s+", " ", clean).strip()
    if not clean:
        return ""
    for sep in ("\u3002", "\uff01", "\uff1f", "! ", "? ", ". ", "\uff1b", "; "):
        idx = clean.find(sep)
        if idx >= 48:
            candidate = clean[: idx + 1].strip()
            if candidate and len(candidate) <= limit:
                return candidate
    if len(clean) <= limit:
        return clean
    return f"{clean[: limit - 1].rstrip()}\u2026"


def _is_google_news_redirect_url(url: str) -> bool:
    """Google News RSS 常给出中间跳转页，直接 fetch 会得到脚本壳而非正文。"""
    u = (url or "").lower()
    return "news.google.com" in u and "articles" in u


def _is_google_news_host(url: str) -> bool:
    """落地 URL 仍停在 news.google.com（含裸域、/read/ 等），需壳页解析或二次请求。"""
    return "news.google.com" in (url or "").lower()


def _extract_publisher_url_from_google_news_shell(html: str) -> str:
    """
    当 HTTP 重定向仍落在 Google 壳页时，从 HTML 中解析媒体原文链接。
    常见：google.com/url?q=、meta refresh、og:url。
    """
    if not html or len(html) < 40:
        return ""
    for rx in (
        r'https?://(?:www\.)?google\.com/url\?[^\s"\'<>]+[?&]q=([^&\s"\'<>\)]+)',
        r'https?://(?:www\.)?google\.[^\s"\'<>/]+/url\?[^\s"\'<>]+[?&]q=([^&\s"\'<>\)]+)',
    ):
        for m in re.finditer(rx, html, re.I):
            try:
                cand = urllib.parse.unquote(m.group(1).strip())
            except Exception:
                continue
            cand = cand.strip()
            if cand.startswith("http") and not _is_google_news_host(cand):
                return cand
    m = re.search(
        r'http-equiv\s*=\s*["\']refresh["\'][^>]+content\s*=\s*["\'][^"\']*url\s*=\s*([^"\';\s]+)',
        html,
        re.I,
    )
    if m:
        try:
            cand = urllib.parse.unquote(m.group(1).strip().strip("'\""))
        except Exception:
            cand = m.group(1).strip().strip("'\"")
        if cand.startswith("http") and not _is_google_news_host(cand):
            return cand
    m = re.search(
        r'<meta\s+property\s*=\s*["\']og:url["\'][^>]+content\s*=\s*["\']([^"\']+)["\']',
        html,
        re.I,
    )
    if m:
        cand = m.group(1).strip()
        if cand.startswith("http") and not _is_google_news_host(cand):
            return cand
    return ""


def _urls_meaningfully_different(a: str, b: str) -> bool:
    """用于判断壳页解析出的候选链接是否与当前页不同（避免死循环指向自身）。"""
    a = (a or "").strip().rstrip("/")
    b = (b or "").strip().rstrip("/")
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return False
    try:
        pa, pb = urllib.parse.urlparse(a), urllib.parse.urlparse(b)
        na, nb = pa.netloc.lower(), pb.netloc.lower()
        if na != nb:
            return True
        return (pa.path or "").rstrip("/") != (pb.path or "").rstrip("/") or pa.query != pb.query
    except Exception:
        return True


def _extract_fallback_article_url_from_shell(html: str, page_url: str) -> str:
    """
    任意中间页/跳转壳的 HTML 中推测真实文章 URL（不限于 Google News）。
    优先复用 google.com/url?q=、meta refresh、og:url；再尝试 link rel=canonical。
    """
    if not html or len(html) < 40:
        return ""
    page_url = (page_url or "").strip()

    cand = _extract_publisher_url_from_google_news_shell(html)
    if (
        cand.startswith("http")
        and not _is_google_news_host(cand)
        and _urls_meaningfully_different(cand, page_url)
    ):
        return cand

    for rx in (
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)["\']',
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
    ):
        m = re.search(rx, html, re.I)
        if not m:
            continue
        raw_h = m.group(1).strip()
        try:
            cand = urllib.parse.urljoin(page_url, raw_h)
        except Exception:
            cand = raw_h
        cand = (cand or "").strip()
        if not cand.startswith("http") or _is_google_news_host(cand):
            continue
        if _urls_meaningfully_different(cand, page_url):
            return cand
    return ""


def _resolve_google_news_for_extract(url: str, timeout: int = ARTICLE_FETCH_TIMEOUT) -> tuple[str, str | None]:
    """
    将 news.google.com/rss/articles/... 解析为可提取正文的页面。

    返回 (effective_url, preloaded_html_or_none)。
    若 HTTP 重定向已落到非 Google 域，preloaded_html 为整页 HTML，可避免再 GET 一次。
    若仍停在 Google 壳页，则尝试从 HTML 解析出媒体 URL（此时第二项为 None）。
    """
    u = (url or "").strip()
    if not u.startswith("http") or not _is_google_news_redirect_url(u):
        return u, None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(u, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final = (resp.geturl() or "").strip()
            raw = resp.read(786432)
            ct = resp.headers.get("Content-Type")
    except Exception:
        return "", None
    html_str = _decode_html_bytes_best_effort(raw, ct)
    # 重定向可能落到裸 https://news.google.com（无 articles 路径），仍须按壳页解析
    if final.startswith("http") and not _is_google_news_host(final):
        return final, html_str
    extracted = _extract_publisher_url_from_google_news_shell(html_str)
    if extracted.startswith("http") and not _is_google_news_host(extracted):
        return extracted, None
    return "", None


def _looks_like_extracted_js_garbage(text: str) -> bool:
    """
    可读性提取失败时，fallback 可能把整页脚本当成「正文」写入。
    此类内容对 LLM 完全无用，必须丢弃。
    """
    if not text or len(text) < 180:
        return False
    t = text.lstrip()
    if t.startswith('"use strict"') or t.startswith("'use strict'"):
        return True
    if "this.default_" in t and "function(_)" in t[:800]:
        return True
    if "_.aa=function" in t or "DotsSplashUi" in t:
        return True
    if t.count("function(") > 35 and len(t) > 4000 and t.count("var ") > 30:
        return True
    return False


def _repair_invalid_stored_content(items: list[dict[str, Any]]) -> bool:
    """
    清理历史数据：无正文、Google News 跳转、误抓 JS 整包等条目整行删除；
    有正文但 summary 为占位符时尝试从正文修复摘要。
    在 _load_news_store 中调用，若有变更则回写磁盘。
    """
    kept: list[dict[str, Any]] = []
    changed = False
    for entry in items:
        if not isinstance(entry, dict):
            changed = True
            continue
        url = str(entry.get("url") or "")
        c = str(entry.get("content") or "")
        summary = str(entry.get("summary") or "")
        if not c.strip():
            changed = True
            continue
        if _looks_like_extracted_js_garbage(c):
            changed = True
            continue
        if _is_placeholder_summary(summary):
            repaired = _build_summary_from_content(c)
            if repaired:
                entry["summary"] = repaired
            else:
                entry["summary"] = ""
            changed = True
        kept.append(entry)

    if changed:
        items[:] = kept
    return changed


# 常见 HTTP charset 别名 → Python codec 名
_HTTP_CHARSET_ALIASES: dict[str, str] = {
    "utf8": "utf-8",
    "gb2312": "gbk",
    "gb_2312": "gbk",
    "euc-cn": "gbk",
    "cp936": "gbk",
    "windows-936": "gbk",
}


def _parse_http_charset(content_type: str | None) -> str | None:
    if not content_type:
        return None
    m = re.search(r"charset\s*=\s*['\"]?([^'\";\s]+)", content_type, re.I)
    if not m:
        return None
    cs = m.group(1).strip().lower()
    if cs.startswith("x-"):
        cs = cs[2:]
    return _HTTP_CHARSET_ALIASES.get(cs, cs)


def _decode_html_bytes_best_effort(raw: bytes, content_type: str | None) -> str:
    """
    按 Content-Type 声明与常见中文编码依次尝试，避免 GBK 页被误当 UTF-8 读出整段乱码。
    """
    ordered: list[str] = []
    cs = _parse_http_charset(content_type)
    if cs:
        ordered.append(cs)
    for enc in ("utf-8", "gb18030", "gbk", "big5"):
        if enc not in ordered:
            ordered.append(enc)
    for enc in ordered:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _sanitize_stored_text(s: str) -> str:
    """
    写入 JSON 前规范化 Unicode，并丢弃「明显解码失败」的文本（大量 U+FFFD）。
    """
    t = unicodedata.normalize("NFC", str(s or ""))
    t = "".join(
        ch
        for ch in t
        if ch in "\n\t\u3000" or ord(ch) >= 32 or unicodedata.category(ch) == "Zs"
    )
    t = t.strip()
    n = len(t)
    if n and t.count("\ufffd") / n > 0.03:
        return ""
    return t


CHUNK_SIZE_TOKENS = 500    # 每个 chunk 的 token 上限
CHUNK_OVERLAP_TOKENS = 50  # chunk 之间的 overlap


# ---------------------------------------------------------------------------
# 存储层：读写单文件 JSON
# ---------------------------------------------------------------------------

def _load_news_store() -> list[dict[str, Any]]:
    """加载 news_store.json，返回条目列表。"""
    if not os.path.exists(NEWS_STORE_FILE):
        return []
    try:
        with open(NEWS_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else []
        if items and _repair_invalid_stored_content(items):
            with NEWS_STORE_LOCK:
                _save_news_store(items)
        return items
    except Exception:
        return []


def _save_news_store(items: list[dict[str, Any]]) -> None:
    """将条目列表写回 news_store.json。"""
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    with open(NEWS_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _make_article_id(item: dict[str, Any]) -> str:
    """根据 url 或 title 生成稳定的 16 位哈希 ID。"""
    key = str(item.get("url") or item.get("title") or "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _prune_old_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """移除超过保留期的条目，并裁剪到最大数量。"""
    cutoff = (datetime.now() - timedelta(days=NEWS_MAX_AGE_DAYS)).isoformat()
    pruned = [e for e in items if str(e.get("stored_at") or "") >= cutoff]
    pruned.sort(key=lambda e: str(e.get("stored_at") or ""), reverse=True)
    return pruned[:NEWS_MAX_ENTRIES]


# ---------------------------------------------------------------------------
# 公共接口：存储新闻（不做 embedding）
# ---------------------------------------------------------------------------

def store_news_items(items: list[dict[str, Any]], fetch_content: bool = True) -> int:
    """
    将新闻条目写入 news_store.json。
    每条记录保存：title, content, published_at, source, url, summary, stored_at。
    不计算任何 embedding。
    若 fetch_content 为 True：正文为 Readability + 纯文本管线；Google News 包装链会先解析到媒体原文 URL 再抓取；解析或提取失败、正文为空则不写入。
    fetch_content 为 False 时同样要求最终正文非空才落库。
    返回本次新增的条目数量。
    """
    if not items:
        return 0

    with NEWS_STORE_LOCK:
        existing = _load_news_store()
        existing_ids = {e["id"] for e in existing if e.get("id")}
        added = 0

        for item in items:
            article_id = _make_article_id(item)
            if article_id in existing_ids:
                continue

            # 仅在需要时才抓取正文；无有效正文则不落库（含 Google News → 媒体站解析）
            content = ""
            stored_url = str(item.get("url") or "")
            if fetch_content:
                from .article_extract import extract_article_plaintext_detailed

                content, canonical_url = extract_article_plaintext_detailed(
                    stored_url, timeout=ARTICLE_FETCH_TIMEOUT
                )
                if not content.strip():
                    continue
                if canonical_url.startswith("http"):
                    stored_url = canonical_url

            clean_content = _sanitize_stored_text(content) if content else ""
            if not clean_content.strip():
                continue
            clean_summary = _sanitize_stored_text(str(item.get("summary") or ""))
            if clean_content and (not clean_summary or _is_placeholder_summary(clean_summary)):
                clean_summary = _build_summary_from_content(clean_content)

            entry: dict[str, Any] = {
                "id": article_id,
                "title": _sanitize_stored_text(str(item.get("title") or "")),
                "url": stored_url,
                "summary": clean_summary,
                "content": clean_content,
                "source": str(item.get("source") or ""),
                "topic": str(item.get("topic") or ""),
                "published_at": str(item.get("published_at") or ""),
                "published_label": str(item.get("published_label") or ""),
                "relevance_score": int(item.get("relevance_score") or 0),
                "match_tags": list(item.get("match_tags") or []),
                "stored_at": datetime.now().isoformat(),
            }
            existing.append(entry)
            existing_ids.add(article_id)
            added += 1

        existing = _prune_old_items(existing)
        _save_news_store(existing)
        return added


# ---------------------------------------------------------------------------
# 文章正文抓取
# ---------------------------------------------------------------------------

def _fetch_article_content(url: str) -> str:
    """
    抓取文章 URL，提取纯文本正文（readability-lxml 对齐 web-content-extractor / Mozilla Readability，
    不足时再 trafilatura）。Google News 包装 URL 会先解析到媒体站再提取。逻辑见 article_extract。
    """
    if not url or not url.startswith("http"):
        return ""

    from .article_extract import extract_article_plaintext_detailed

    text, _ = extract_article_plaintext_detailed(url, timeout=ARTICLE_FETCH_TIMEOUT)
    if not text:
        return ""

    if len(text) > ARTICLE_CONTENT_MAX_CHARS:
        text = f"{text[: ARTICLE_CONTENT_MAX_CHARS - 1].rstrip()}…"
    return text


# ---------------------------------------------------------------------------
# 分块工具（500 token / overlap=50）
# ---------------------------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """
    粗略估算 token 数量（中英文混合文本）：
    - CJK 字符：每字 1 token
    - 拉丁单词：每词 1 token
    """
    cjk_count = len(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef]", text))
    rest = re.sub(r"[\u4e00-\u9fff\u3400-\u4dbf\uff00-\uffef\s]", " ", text)
    latin_words = len([w for w in rest.split() if w])
    return cjk_count + latin_words


def _chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE_TOKENS,
    overlap: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """
    将文本按句子边界切分为带 overlap 的 chunk 列表。
    - chunk_size: 每块约 500 token
    - overlap:    相邻块重叠约 50 token
    """
    if not text or not text.strip():
        return []

    # 优先按句子边界（。！？换行）切分
    raw_segs = re.split(r"(?<=[。！？\n])\s*", text.strip())
    segments = [s.strip() for s in raw_segs if s.strip()]
    if not segments:
        return [text.strip()]

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for seg in segments:
        seg_tokens = _estimate_tokens(seg)

        # 单个句子超长时强制按字符切分
        if seg_tokens > chunk_size:
            if current:
                chunks.append("".join(current))
                current, current_tokens = [], 0
            approx_ratio = len(seg) / max(seg_tokens, 1)
            char_limit = int(chunk_size * approx_ratio)
            overlap_chars = int(overlap * approx_ratio)
            pos = 0
            while pos < len(seg):
                chunks.append(seg[pos: pos + char_limit])
                pos += max(char_limit - overlap_chars, 1)
            continue

        # 当前块加上本句会超出 chunk_size：先保存当前块
        if current_tokens + seg_tokens > chunk_size and current:
            chunks.append("".join(current))
            # 保留尾部 overlap 部分作为下一块的开头
            overlap_segs: list[str] = []
            overlap_tokens = 0
            for s in reversed(current):
                st = _estimate_tokens(s)
                if overlap_tokens + st <= overlap:
                    overlap_segs.insert(0, s)
                    overlap_tokens += st
                else:
                    break
            current, current_tokens = overlap_segs, overlap_tokens

        current.append(seg)
        current_tokens += seg_tokens

    if current:
        chunks.append("".join(current))

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Embedding & 向量工具
# ---------------------------------------------------------------------------

def _get_embedding(text: str) -> list[float] | None:
    """调用 OpenRouter baai/bge-m3 接口，返回 embedding 向量。"""
    if not text or not text.strip():
        return None
    try:
        payload = json.dumps({
            "model": EMBEDDING_MODEL,
            "input": text[:2048],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{EMBEDDING_BASE_URL}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {EMBEDDING_API_KEY}",
                "HTTP-Referer": "https://career-platform.local",
                "X-Title": "Career Platform",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        data = result.get("data")
        if isinstance(data, list) and data:
            emb = data[0].get("embedding")
            if isinstance(emb, list) and emb:
                return [float(v) for v in emb]
    except Exception:
        pass
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# Chunk 向量缓存（避免重复调用 Embedding API）
# ---------------------------------------------------------------------------

def _chunk_hash(chunk_text: str) -> str:
    return hashlib.sha1(chunk_text.encode("utf-8")).hexdigest()[:16]


def _load_chunks_cache() -> dict[str, list[float]]:
    """加载 chunk embedding 缓存 {chunk_hash: embedding}。"""
    if not os.path.exists(NEWS_CHUNKS_CACHE_FILE):
        return {}
    try:
        with open(NEWS_CHUNKS_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_chunks_cache(cache: dict[str, list[float]]) -> None:
    os.makedirs(APP_DATA_DIR, exist_ok=True)
    with open(NEWS_CHUNKS_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 公共接口：RAG 检索（画像/查询与资讯对齐时使用；行业总览不走此路径）
# ---------------------------------------------------------------------------

def search_news_for_agent(
    query: str,
    top_k: int = 10,
    max_age_days: int = 7,
    min_score: float = 0.28,
) -> list[dict[str, Any]]:
    """
    向量检索入口：用 query 与新闻分块做 embedding 相似度匹配。

    流程：
    1. 读取 news_store.json，过滤 max_age_days 内的新闻
    2. 将每篇文章（title + summary + content）按 500 token / overlap=50 分块
    3. 对每个 chunk 做 embedding（已有缓存则跳过 API 调用）
    4. 对 query 做 embedding
    5. 余弦相似度排序，返回 top_k 结果
       每条结果：{chunk_text, title, source, published_at, url, score}
    """
    all_news = _load_news_store()
    if not all_news:
        return []

    # 按存储时间过滤（回退：若近期无内容则取全部最新的 50 条）
    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
    recent = [
        n for n in all_news
        if str(n.get("stored_at") or n.get("published_at") or "") >= cutoff
    ]
    if not recent:
        recent = sorted(
            all_news,
            key=lambda n: str(n.get("stored_at") or ""),
            reverse=True,
        )[:50]

    # ---- 构建 chunk 语料库 ----
    corpus: list[dict[str, Any]] = []
    for article in recent:
        title = str(article.get("title") or "")
        summary = str(article.get("summary") or "")
        if _is_placeholder_summary(summary):
            summary = ""
        content = str(article.get("content") or "")
        full_text = f"{title}。{summary}。{content}".strip("。 ")
        if not full_text:
            continue
        for chunk in _chunk_text(full_text):
            corpus.append({
                "chunk_text": chunk,
                "chunk_hash": _chunk_hash(chunk),
                "title": title,
                "source": str(article.get("source") or ""),
                "published_at": str(
                    article.get("published_label") or article.get("published_at") or ""
                ),
                "url": str(article.get("url") or ""),
            })

    if not corpus:
        return []

    # ---- 加载缓存 & 对未缓存的 chunk 做 embedding ----
    cache = _load_chunks_cache()
    cache_updated = False
    for item in corpus:
        h = item["chunk_hash"]
        if h in cache:
            item["embedding"] = cache[h]
        else:
            emb = _get_embedding(item["chunk_text"])
            item["embedding"] = emb or []
            if emb:
                cache[h] = emb
                cache_updated = True

    if cache_updated:
        try:
            _save_chunks_cache(cache)
        except Exception:
            pass

    # ---- 无 query 时直接返回最新的 top_k 块 ----
    query = str(query or "").strip()
    if not query:
        return [
            {k: v for k, v in item.items() if k != "embedding" and k != "chunk_hash"}
            for item in corpus[:top_k]
        ]

    # ---- Embed query & 计算相似度 ----
    query_emb = _get_embedding(query)
    results: list[dict[str, Any]] = []
    for item in corpus:
        emb = item.get("embedding") or []
        if query_emb and emb:
            score = _cosine_similarity(query_emb, emb)
        else:
            # 关键词回退
            text_lower = item["chunk_text"].lower()
            words = query.lower().split()
            hits = sum(1 for w in words if len(w) > 1 and w in text_lower)
            score = hits / max(len(words), 1) * 0.55

        if score >= min_score:
            results.append({
                "chunk_text": item["chunk_text"],
                "title": item["title"],
                "source": item["source"],
                "published_at": item["published_at"],
                "url": item["url"],
                "score": round(score, 4),
            })

    results.sort(key=lambda r: r["score"], reverse=True)
    # 去重：同一篇文章只保留得分最高的 chunk
    seen_titles: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in results:
        key = r["title"][:40]
        if key not in seen_titles:
            deduped.append(r)
            seen_titles.add(key)
        if len(deduped) >= top_k:
            break

    return deduped


def format_rag_context(
    chunks: list[dict[str, Any]],
    *,
    heading: str | None = None,
) -> str:
    """
    将 search_news_for_agent 返回的 chunk 列表格式化为
    适合传入 LLM 的 Markdown 文本。
    """
    if not chunks:
        return "（暂无相关新闻数据）"
    h = heading if heading is not None else "### 近期行业资讯（RAG 检索结果）\n"
    if not h.endswith("\n"):
        h = h + "\n"
    lines = [h]
    for i, c in enumerate(chunks, 1):
        title = c.get("title") or ""
        source = c.get("source") or ""
        pub = c.get("published_at") or ""
        text = c.get("chunk_text") or ""
        score = c.get("score", 0)
        lines.append(f"**[{i}] {title}**")
        lines.append(f"来源：{source}  时间：{pub}  相关度：{score:.2f}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def get_profile_aligned_news_rag_context(
    profile_payload: dict[str, Any] | None,
    role_payload: list[dict[str, Any]] | None = None,
    *,
    focus_role_id: str = "",
    top_k: int = 5,
    min_score: float = 0.34,
    max_age_days: int = 14,
) -> str:
    """
    用用户目标方向、专业、城市（及可选目标岗位标题/描述）拼成查询，对 news_store 做向量检索。
    仅当存在达到 min_score 的匹配块时才返回 Markdown；否则返回空串，避免「无强相关仍塞 RAG」。

    用途：与「行业动态摘要归纳」（get_recent_news_context）区分——后者用于行业分析总览；
    本函数适用于需要「个人画像 ↔ 资讯」对齐的步骤（如职业定位细化）。
    """
    basics = (profile_payload or {}).get("basics") or {}
    parts: list[str] = [
        str(basics.get("targetDirection") or basics.get("target_direction") or ""),
        str(basics.get("major") or ""),
        str(basics.get("targetCity") or basics.get("target_city") or ""),
    ]
    roles = role_payload or []
    if roles:
        picked = None
        if focus_role_id:
            for r in roles:
                if str(r.get("id") or "") == focus_role_id:
                    picked = r
                    break
        if picked is None:
            picked = roles[0]
        parts.append(str(picked.get("name") or picked.get("title") or ""))
        desc = str(picked.get("description") or picked.get("summary") or picked.get("jd") or "")
        if desc:
            parts.append(desc[:280])

    query = " ".join(p for p in parts if p).strip()
    if len(query) < 3:
        return ""

    if not _load_news_store():
        return ""

    chunks = search_news_for_agent(
        query,
        top_k=top_k,
        max_age_days=max_age_days,
        min_score=min_score,
    )
    if not chunks:
        return ""
    return format_rag_context(
        chunks,
        heading="### 与画像查询相关的新闻摘录（向量检索，仅作交叉验证）\n",
    )


# ---------------------------------------------------------------------------
# 兼容接口：保留 get_recent_news_context（供 orchestrator 回退使用）
# ---------------------------------------------------------------------------

# 职业报告编排注入「行业分析」时，单条正文节选上限（非 RAG；避免 prompt 爆炸）
NEWS_CONTEXT_SNIPPET_MAX_CHARS = 2000


def get_recent_news_context(
    topics: list[str] | None = None,
    max_items: int = 15,
    max_age_days: int = 7,
) -> tuple[str, int]:
    """
    从 news_store.json 读取最近新闻，格式化为 Markdown 文本（时间序 + 节选归纳，非向量 RAG）。
    供 career-report 中「行业分析师」做外部环境总览。

    注意：与仪表盘用的 career_news_snapshot.json（约 50 条 RSS）不是同一数据源；
    此处只读已写入 news_store 的条目（抓取快照时后台 store_news_items 异步写入），
    且 max_items 会截断条数，单条正文仅节选 NEWS_CONTEXT_SNIPPET_MAX_CHARS。

    Returns:
        (markdown_text, used_item_count) — used_item_count 为实际写入上下文的条数。
    """
    all_news = _load_news_store()
    if not all_news:
        return "（暂无本地新闻数据）", 0

    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
    recent = [
        n for n in all_news
        if str(n.get("stored_at") or "") >= cutoff
    ]
    recent.sort(
        key=lambda e: str(e.get("published_at") or e.get("stored_at") or ""),
        reverse=True,
    )

    if topics:
        filtered = []
        for n in recent:
            topic = str(n.get("topic") or "").lower()
            tags = " ".join(str(t).lower() for t in (n.get("match_tags") or []))
            if any(t.lower() in topic or t.lower() in tags for t in topics):
                filtered.append(n)
        if filtered:
            recent = filtered

    recent = recent[:max_items]
    if not recent:
        return "（最近新闻数据库无匹配内容）", 0

    cap = NEWS_CONTEXT_SNIPPET_MAX_CHARS
    lines = ["### 近期行业资讯摘要\n"]
    for n in recent:
        title = str(n.get("title") or "")
        summary = str(n.get("summary") or "").strip()
        source = str(n.get("source") or "")
        topic = str(n.get("topic") or "")
        pub = str(n.get("published_label") or n.get("published_at") or "")
        snippet = str(n.get("content") or "").strip()
        if snippet and _looks_like_extracted_js_garbage(snippet):
            snippet = ""
        if snippet:
            snippet = snippet[:cap] + ("..." if len(snippet) > cap else "")

        lines.append(f"**{title}**")
        lines.append(f"- 来源：{source} | 话题：{topic} | 时间：{pub}")
        if summary and not _is_placeholder_summary(summary):
            lines.append(f"- 摘要：{summary}")
        if snippet:
            lines.append(f"- 内容节选：{snippet}")
        lines.append("")

    return "\n".join(lines), len(recent)


# ---------------------------------------------------------------------------
# 统计接口
# ---------------------------------------------------------------------------

def get_kb_stats() -> dict[str, Any]:
    """返回新闻存储的基础统计信息。"""
    items = _load_news_store()
    cache = _load_chunks_cache()
    with_content = sum(1 for n in items if n.get("content"))
    return {
        "total_entries": len(items),
        "with_content": with_content,
        "cached_chunk_embeddings": len(cache),
        "store_file": NEWS_STORE_FILE,
        "chunks_cache_file": NEWS_CHUNKS_CACHE_FILE,
    }


# ---------------------------------------------------------------------------
# 向后兼容别名：server.py 的 /api/news-kb/search 端点使用
# ---------------------------------------------------------------------------

def search_news_kb(
    query: str,
    top_k: int = 8,
    min_score: float = 0.28,
    topic_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    向后兼容接口，内部调用 search_news_for_agent。
    topic_filter 参数通过将 topic 附加到 query 实现粗粒度过滤。
    """
    full_query = f"{topic_filter} {query}".strip() if topic_filter else query
    return search_news_for_agent(full_query, top_k=top_k, min_score=min_score)
