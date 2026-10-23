"""
网页正文提取（由 web-content-extractor 思路迁移：Mozilla Readability + 纯文本）。

原 Next.js 实现：fetch → JSDOM → @mozilla/readability → article.textContent → 空白折叠。
Python 使用 readability-lxml（同源算法族）得到摘要 HTML，再用 lxml 取 text_content，
仅返回纯文本字符串；失败时可回退 trafilatura.extract（仍为纯文本）。

不依赖 Node；不返回 HTML 片段以外的结构化字段写入 news_store。
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request

# 与 news_kb 中正文可用性阈值一致：过短视为未提取到有效正文
MIN_PLAIN_TEXT_LEN = 80

MAX_HTML_BYTES = 524288

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _collapse_ws(text: str) -> str:
    """对齐原项目 cleanText：连续空白折叠为单空格。"""
    return re.sub(r"[\n\s]+", " ", (text or "").strip())


def _summary_html_to_plain(summary_html: str) -> str:
    if not summary_html or not summary_html.strip():
        return ""
    try:
        from lxml import html as lxml_html

        root = lxml_html.fromstring(summary_html)
        raw = root.text_content()
    except Exception:
        return ""
    return _collapse_ws(raw)


def _readability_plaintext(html: str, url: str) -> str:
    try:
        from readability.readability import Document
    except ImportError:
        return ""

    try:
        doc = Document(html, url=url or None)
        summary = doc.summary()
    except Exception:
        return ""

    if not summary:
        return ""
    text = _summary_html_to_plain(summary)
    return text if len(text) >= MIN_PLAIN_TEXT_LEN else ""


def _trafilatura_plaintext(html: str) -> str:
    try:
        import trafilatura
    except ImportError:
        return ""

    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
    except Exception:
        return ""

    text = _collapse_ws(str(text or ""))
    return text if len(text) >= MIN_PLAIN_TEXT_LEN else ""


def _fetch_html(url: str, timeout: int) -> tuple[str | None, str | None, str | None]:
    """GET 网页。返回 (html, 重定向后的最终 URL, error)；成功时 error 为 None。"""
    from . import news_kb as nk

    try:
        req = urllib.request.Request(url, headers=_DEFAULT_HEADERS, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            final_url = (resp.geturl() or "").strip() or None
            raw = resp.read(MAX_HTML_BYTES)
            ct = resp.headers.get("Content-Type")
        html = nk._decode_html_bytes_best_effort(raw, ct)
        return html, final_url, None
    except urllib.error.HTTPError as e:
        return None, None, f"http {e.code}"
    except Exception as e:
        return None, None, str(e)


def _html_to_article_plaintext(html: str, page_url: str) -> str:
    """对整页 HTML 跑 Readability → trafilatura → sanitize / JS 垃圾过滤。"""
    from . import news_kb as nk

    text = _readability_plaintext(html, page_url)
    if not text:
        text = _trafilatura_plaintext(html)
    text = nk._sanitize_stored_text(text)
    if not text or nk._looks_like_extracted_js_garbage(text):
        return ""
    return text


def extract_article_plaintext_detailed(url: str, *, timeout: int = 8) -> tuple[str, str]:
    """
    抓取 URL，提取纯文本正文；返回 (正文, 实际落地文章的规范化 URL)。

    先对入口 URL 直接 GET（含 HTTP 重定向）并做 Readability / trafilatura；
    若得不到可用正文，再尝试：Google News 专用解析、以及从壳页 HTML 抽取真实文章链接后二次 GET。
    失败返回 ("", "").
    """
    from . import news_kb as nk

    u = str(url or "").strip()
    if not u.startswith("http"):
        return "", ""

    html, final_u, _err = _fetch_html(u, timeout)
    page_url = (final_u or u).strip()

    if html:
        text = _html_to_article_plaintext(html, page_url)
        if text:
            return text, page_url

    # 首跳无正文：解析中间页/跳转壳上的真实文章 URL 再抓（不限于 Google News）
    candidates: list[tuple[str, str | None]] = []

    if nk._is_google_news_redirect_url(u):
        eff, pre = nk._resolve_google_news_for_extract(u, timeout)
        if eff.startswith("http") and not nk._is_google_news_host(eff):
            candidates.append((eff, pre))

    if html:
        alt = nk._extract_fallback_article_url_from_shell(html, page_url)
        if alt.startswith("http"):
            candidates.append((alt, None))

    seen: set[str] = set()

    def _norm_key(x: str) -> str:
        return x.rstrip("/").lower()

    for eff, pre in candidates:
        k = _norm_key(eff)
        if not k or k in seen:
            continue
        seen.add(k)

        body = pre
        use_url = eff
        if body is None:
            h2, fu2, e2 = _fetch_html(eff, timeout)
            if not h2:
                continue
            body = h2
            if fu2 and fu2.startswith("http"):
                use_url = fu2.strip()

        text = _html_to_article_plaintext(body, use_url)
        if text:
            return text, use_url

    return "", ""


def extract_article_plaintext(url: str, *, timeout: int = 8) -> str:
    """
    抓取 URL，提取**仅纯文本**正文；不可用则返回空串。

    顺序：直抓 → 无正文时再走壳页/跳转解析后二次抓取。
    """
    text, _ = extract_article_plaintext_detailed(url, timeout=timeout)
    return text
