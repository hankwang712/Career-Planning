"""
News Knowledge Base

Stores fetched news articles with their embeddings for semantic retrieval.
Used by the Industry Analyst agent to access relevant news context.

Embedding model: baai/bge-m3 via OpenRouter
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")
NEWS_KB_DIR = os.path.join(APP_DATA_DIR, "news_kb")
NEWS_KB_INDEX_FILE = os.path.join(NEWS_KB_DIR, "index.json")
NEWS_KB_LOCK = threading.Lock()

EMBEDDING_MODEL = "baai/bge-m3"
EMBEDDING_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_API_KEY = "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"

KB_MAX_ENTRIES = 500          # max articles to keep
KB_MAX_AGE_DAYS = 45          # drop articles older than this
KB_ARTICLE_FETCH_TIMEOUT = 8  # seconds to fetch article body


def _ensure_kb_dir():
    os.makedirs(NEWS_KB_DIR, exist_ok=True)


def _load_index() -> list[dict[str, Any]]:
    """Load the KB index (list of article entries)."""
    _ensure_kb_dir()
    if not os.path.exists(NEWS_KB_INDEX_FILE):
        return []
    try:
        with open(NEWS_KB_INDEX_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_index(entries: list[dict[str, Any]]) -> None:
    _ensure_kb_dir()
    with open(NEWS_KB_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _article_file_path(article_id: str) -> str:
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in article_id)[:64]
    return os.path.join(NEWS_KB_DIR, f"{safe_id}.json")


def _load_article(article_id: str) -> dict[str, Any] | None:
    path = _article_file_path(article_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_article(article_id: str, data: dict[str, Any]) -> None:
    _ensure_kb_dir()
    path = _article_file_path(article_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_embedding(text: str) -> list[float] | None:
    """Call OpenRouter embeddings API with baai/bge-m3."""
    if not text or not text.strip():
        return None
    try:
        payload = json.dumps({
            "model": EMBEDDING_MODEL,
            "input": text[:2048],  # truncate for safety
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


def _fetch_article_content(url: str) -> str:
    """Try to fetch a lightweight text version of the article URL."""
    if not url or not url.startswith("http"):
        return ""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=KB_ARTICLE_FETCH_TIMEOUT) as resp:
            raw = resp.read(32768)  # read up to 32KB
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = raw.decode("gbk", errors="replace")
        # Strip HTML tags roughly
        import re
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000]
    except Exception:
        return ""


def _make_article_id(item: dict[str, Any]) -> str:
    """Generate a stable ID for a news item."""
    import hashlib
    key = str(item.get("url") or item.get("title") or "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _prune_old_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove entries older than KB_MAX_AGE_DAYS and keep only KB_MAX_ENTRIES."""
    cutoff = (datetime.now() - timedelta(days=KB_MAX_AGE_DAYS)).isoformat()
    pruned = [e for e in entries if str(e.get("stored_at") or "") >= cutoff]
    pruned.sort(key=lambda e: str(e.get("stored_at") or ""), reverse=True)
    return pruned[:KB_MAX_ENTRIES]


def store_news_items(items: list[dict[str, Any]], fetch_content: bool = True) -> int:
    """
    Store news items to the knowledge base.
    Fetches article content and computes embeddings for each new item.
    Returns number of newly added items.
    """
    if not items:
        return 0

    with NEWS_KB_LOCK:
        entries = _load_index()
        existing_ids = {e["id"] for e in entries if e.get("id")}
        added = 0

        for item in items:
            article_id = _make_article_id(item)
            if article_id in existing_ids:
                continue

            # Fetch article content
            content = ""
            if fetch_content:
                url = str(item.get("url") or "")
                content = _fetch_article_content(url)

            # Build text for embedding
            title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            topic = str(item.get("topic") or "").strip()
            embed_text = f"{title}\n{topic}\n{summary}\n{content[:500]}"

            # Get embedding
            embedding = _get_embedding(embed_text)

            entry = {
                "id": article_id,
                "title": title,
                "url": str(item.get("url") or ""),
                "summary": summary,
                "source": str(item.get("source") or ""),
                "topic": topic,
                "published_at": str(item.get("published_at") or ""),
                "published_label": str(item.get("published_label") or ""),
                "relevance_score": int(item.get("relevance_score") or 0),
                "match_tags": list(item.get("match_tags") or []),
                "stored_at": datetime.now().isoformat(),
                "has_content": bool(content),
                "has_embedding": bool(embedding),
            }
            entries.append(entry)
            existing_ids.add(article_id)
            added += 1

            # Save article data (with content and embedding) in separate file
            article_data = dict(entry)
            article_data["content"] = content
            article_data["embedding"] = embedding or []
            _save_article(article_id, article_data)

        entries = _prune_old_entries(entries)
        _save_index(entries)
        return added


def search_news_kb(
    query: str,
    top_k: int = 8,
    min_score: float = 0.35,
    topic_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    Semantic search the news KB using query embedding.
    Falls back to keyword search if embedding fails.
    Returns list of article dicts with 'score' field.
    """
    query = str(query or "").strip()
    if not query:
        return []

    entries = _load_index()
    if not entries:
        return []

    # Get query embedding
    query_emb = _get_embedding(query)

    results = []
    for entry in entries:
        if topic_filter and topic_filter.lower() not in str(entry.get("topic") or "").lower():
            continue

        article = _load_article(entry["id"])
        if not article:
            continue

        article_emb = article.get("embedding") or []

        if query_emb and article_emb:
            score = _cosine_similarity(query_emb, article_emb)
        else:
            # Fallback: keyword matching
            text = (
                str(entry.get("title") or "") + " " +
                str(entry.get("summary") or "") + " " +
                str(entry.get("topic") or "")
            ).lower()
            words = query.lower().split()
            hits = sum(1 for w in words if w in text)
            score = hits / max(len(words), 1) * 0.8

        if score >= min_score:
            result = dict(entry)
            result["content"] = str(article.get("content") or "")
            result["score"] = round(score, 4)
            results.append(result)

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def get_recent_news_context(
    topics: list[str] | None = None,
    max_items: int = 15,
    max_age_days: int = 7,
) -> str:
    """
    Build a news context string for the Industry Analyst agent.
    Returns formatted Markdown text of recent relevant news.
    """
    entries = _load_index()
    if not entries:
        return "（暂无本地新闻知识库内容）"

    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
    recent = [e for e in entries if str(e.get("stored_at") or "") >= cutoff]
    recent.sort(key=lambda e: str(e.get("published_at") or e.get("stored_at") or ""), reverse=True)

    if topics:
        filtered = []
        for e in recent:
            topic = str(e.get("topic") or "").lower()
            tags = [str(t).lower() for t in (e.get("match_tags") or [])]
            if any(t.lower() in topic or t.lower() in " ".join(tags) for t in topics):
                filtered.append(e)
        if filtered:
            recent = filtered

    recent = recent[:max_items]
    if not recent:
        return "（最近新闻知识库无匹配内容）"

    lines = ["### 近期行业资讯摘要（来自本地知识库）\n"]
    for e in recent:
        article = _load_article(e["id"])
        content_snippet = ""
        if article:
            raw = str(article.get("content") or "").strip()
            if raw:
                content_snippet = raw[:300] + ("..." if len(raw) > 300 else "")

        pub = str(e.get("published_label") or e.get("published_at") or "")
        source = str(e.get("source") or "")
        topic = str(e.get("topic") or "")
        title = str(e.get("title") or "")
        summary = str(e.get("summary") or "").strip()

        lines.append(f"**{title}**")
        lines.append(f"- 来源：{source} | 话题：{topic} | 时间：{pub}")
        if summary and summary != "点击查看原文>":
            lines.append(f"- 摘要：{summary}")
        if content_snippet:
            lines.append(f"- 内容：{content_snippet}")
        lines.append("")

    return "\n".join(lines)


def get_kb_stats() -> dict[str, Any]:
    """Return basic stats about the knowledge base."""
    entries = _load_index()
    with_embedding = sum(1 for e in entries if e.get("has_embedding"))
    with_content = sum(1 for e in entries if e.get("has_content"))
    return {
        "total_entries": len(entries),
        "with_embedding": with_embedding,
        "with_content": with_content,
        "kb_dir": NEWS_KB_DIR,
    }
