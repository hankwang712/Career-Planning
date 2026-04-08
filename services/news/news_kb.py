"""
News Storage & RAG Module

存储层：所有新闻条目存入单个 JSON 文件（news_store.json），
        每条记录仅保存 title / content / published_at / source / url / summary。
        存储时 **不做 embedding**。

RAG 层：行业分析 Agent 调用 search_news_for_agent() 时，才触发：
        1. 读取 news_store.json
        2. 将每篇文章拼合后按 500 token / overlap=50 分块
        3. 对每个 chunk 做 embedding（结果缓存到 news_chunks_cache.json）
        4. 对 query 做 embedding，余弦相似度排序
        5. 返回 top_k 相关 chunk 供 Agent 使用
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# 路径 & 常量
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")

NEWS_STORE_FILE = os.path.join(APP_DATA_DIR, "news_store.json")
NEWS_CHUNKS_CACHE_FILE = os.path.join(APP_DATA_DIR, "news_chunks_cache.json")
NEWS_STORE_LOCK = threading.Lock()

EMBEDDING_MODEL = "baai/bge-m3"
EMBEDDING_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_API_KEY = "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"

NEWS_MAX_ENTRIES = 500     # 最多保留条数
NEWS_MAX_AGE_DAYS = 45     # 超过此天数的条目会被裁剪
ARTICLE_FETCH_TIMEOUT = 8  # 抓取正文的超时（秒）

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
        return data if isinstance(data, list) else []
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

            # 仅在需要时才抓取正文
            content = ""
            if fetch_content:
                url = str(item.get("url") or "")
                content = _fetch_article_content(url)

            entry: dict[str, Any] = {
                "id": article_id,
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or ""),
                "summary": str(item.get("summary") or "").strip(),
                "content": content,
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
    """抓取文章 URL 并提取纯文本（最多 3000 字符）。"""
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
        with urllib.request.urlopen(req, timeout=ARTICLE_FETCH_TIMEOUT) as resp:
            raw = resp.read(32768)
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = raw.decode("gbk", errors="replace")
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:3000]
    except Exception:
        return ""


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
# 公共接口：RAG 检索（供行业分析 Agent 使用）
# ---------------------------------------------------------------------------

def search_news_for_agent(
    query: str,
    top_k: int = 10,
    max_age_days: int = 7,
    min_score: float = 0.28,
) -> list[dict[str, Any]]:
    """
    行业分析 Agent 的 RAG 检索入口。

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


def format_rag_context(chunks: list[dict[str, Any]]) -> str:
    """
    将 search_news_for_agent 返回的 chunk 列表格式化为
    适合传入 LLM 的 Markdown 文本。
    """
    if not chunks:
        return "（暂无相关新闻数据）"
    lines = ["### 近期行业资讯（RAG 检索结果）\n"]
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


# ---------------------------------------------------------------------------
# 兼容接口：保留 get_recent_news_context（供 orchestrator 回退使用）
# ---------------------------------------------------------------------------

def get_recent_news_context(
    topics: list[str] | None = None,
    max_items: int = 15,
    max_age_days: int = 7,
) -> str:
    """
    从 news_store.json 读取最近新闻，格式化为 Markdown 文本。
    （非 RAG 版本，不做 embedding，供 orchestrator 回退 / 调试使用。）
    """
    all_news = _load_news_store()
    if not all_news:
        return "（暂无本地新闻数据）"

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
        return "（最近新闻数据库无匹配内容）"

    lines = ["### 近期行业资讯摘要\n"]
    for n in recent:
        title = str(n.get("title") or "")
        summary = str(n.get("summary") or "").strip()
        source = str(n.get("source") or "")
        topic = str(n.get("topic") or "")
        pub = str(n.get("published_label") or n.get("published_at") or "")
        snippet = str(n.get("content") or "").strip()
        if snippet:
            snippet = snippet[:300] + ("..." if len(snippet) > 300 else "")

        lines.append(f"**{title}**")
        lines.append(f"- 来源：{source} | 话题：{topic} | 时间：{pub}")
        if summary and summary != "点击查看原文>":
            lines.append(f"- 摘要：{summary}")
        if snippet:
            lines.append(f"- 内容节选：{snippet}")
        lines.append("")

    return "\n".join(lines)


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
