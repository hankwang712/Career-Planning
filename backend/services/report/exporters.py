from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path
from typing import Any, Optional

from ..paths import REPORT_IMAGE_DIR


def _strip_pipeline_summary_lines(text: str) -> str:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        t = line.strip()
        if re.match(r"^(MATCH_SUMMARY|PATH_SUMMARY)\s*:", t, re.I):
            continue
        lines.append(line)
    out = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def strip_machine_readable_markdown_sections(text: str) -> str:
    """Remove markdown sections whose heading contains「机器可读」(pipeline JSON blocks)."""
    lines = str(text or "").split("\n")
    out: list[str] = []
    skip_depth: Optional[int] = None
    heading_re = re.compile(r"^(#{1,6})\s+(.*)$")
    i = 0
    while i < len(lines):
        line = lines[i]
        m = heading_re.match(line)
        if m:
            depth = len(m.group(1))
            title = m.group(2) or ""
            if skip_depth is not None:
                if depth <= skip_depth:
                    skip_depth = None
                    i -= 1
                    continue
                i += 1
                continue
            if "机器可读" in title:
                skip_depth = depth
                i += 1
                continue
        if skip_depth is not None:
            i += 1
            continue
        out.append(line)
        i += 1
    joined = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


_BR_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def _is_gfm_table_separator_line(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|"):
        return False
    return bool(re.search(r"\|\s*:?-{2,}", s))


def _is_likely_gfm_table_row(line: str) -> bool:
    s = line.strip()
    if not s.startswith("|") or s.count("|") < 2:
        return False
    if _is_gfm_table_separator_line(line):
        return False
    return True


def normalize_br_tags_in_markdown(text: str) -> str:
    """将模型常输出的 HTML <br> 转为纯 Markdown 友好形式，避免 .md 源文件与简易 HTML 导出中出现裸标签。"""
    lines = str(text or "").split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        if _is_likely_gfm_table_row(line):
            out.append(_BR_TAG_RE.sub("；", line))
        else:
            out.append(_BR_TAG_RE.sub("\n", line))
    joined = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", joined)


def _extract_inline_images_to_local(text: str) -> str:
    """将 Markdown/HTML 中内嵌的 base64 图片保存到本地 static/img/report/ 并替换路径。"""
    import base64
    import random
    import string

    report_image_dir = REPORT_IMAGE_DIR
    report_image_dir.mkdir(parents=True, exist_ok=True)

    md_pattern = re.compile(r"!\[([^\]]*)\]\((data:image/([a-zA-Z0-9+.-]+);base64,([^)\s]+))\)")
    html_pattern = re.compile(r'<img[^>]*src="(data:image/([a-zA-Z0-9+.-]+);base64,([^"\s]+))"[^>]*>')

    def _save(mime_subtype: str, encoded: str) -> str | None:
        ext = mime_subtype.replace("jpeg", "jpg") if mime_subtype else "png"
        if not ext or len(ext) > 5:
            ext = "png"
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        filename = f"inline_{rand}.{ext}"
        target_path = report_image_dir / filename
        try:
            data = base64.b64decode(encoded)
            target_path.write_bytes(data)
            return f"/static/img/report/{filename}"
        except Exception:
            return None

    def _md_replace(match):
        alt = match.group(1)
        mime = match.group(3)
        encoded = match.group(4)
        local = _save(mime, encoded)
        return f"![{alt}]({local})" if local else match.group(0)

    def _html_replace(match):
        mime = match.group(3)
        encoded = match.group(4)
        local = _save(mime, encoded)
        return f"![配图]({local})" if local else match.group(0)

    text = md_pattern.sub(_md_replace, text)
    text = html_pattern.sub(_html_replace, text)
    return text


def markdown_for_user_reading(text: str) -> str:
    """HTML/DOCX export: same human-facing text as the report reader (no machine JSON sections)."""
    cleaned = _extract_inline_images_to_local(text)
    cleaned = strip_machine_readable_markdown_sections(cleaned)
    cleaned = normalize_br_tags_in_markdown(cleaned)
    return _strip_pipeline_summary_lines(cleaned)


_DOCX_HEADING_LINE_RE = re.compile(r"^(##|###)\s+")


def docx_prepare_markdown(text: str) -> str:
    """DOCX 专用：在 ``##`` 与 ``###`` 标题前插入空行，便于 Word 中区段分隔。"""
    lines = str(text or "").splitlines()
    out: list[str] = []
    for line in lines:
        if _DOCX_HEADING_LINE_RE.match(line):
            if out and out[-1].strip() != "":
                out.append("")
        out.append(line)
    result = "\n".join(out)
    if str(text or "").endswith("\n"):
        result += "\n"
    return result


DOCX_MCP_CONDA_ENV = os.environ.get("CAREER_REPORT_DOCX_CONDA_ENV", "yolov11").strip() or "yolov11"
DOCX_MCP_PYTHON = os.environ.get("CAREER_REPORT_DOCX_PYTHON", "").strip()


def _resolve_docx_python(conda_env: str) -> str:
    override = DOCX_MCP_PYTHON
    if override and Path(override).exists():
        return override

    conda_exe = Path(os.environ.get("CONDA_EXE") or "conda")
    if conda_exe.name.lower() == "conda.exe":
        conda_root = conda_exe.parent.parent
        env_python = conda_root / "envs" / conda_env / "python.exe"
        if env_python.exists():
            return str(env_python)

    candidate = shutil.which("python")
    if candidate:
        return candidate
    raise RuntimeError(f"Unable to locate Python interpreter for conda env '{conda_env}'")


def _iter_document_sections(report: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    document = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    sections = document.get("sections")
    if isinstance(sections, dict):
        ordered_keys = [
            "industry_analysis",
            "career_positioning",
            "resume_evidence",
            "competency_profile",
            "role_match",
            "path_plan",
        ]
        ordered: list[tuple[str, dict[str, Any]]] = []
        seen: set[str] = set()
        for key in ordered_keys + list(sections.keys()):
            if key in seen:
                continue
            seen.add(key)
            section = sections.get(key)
            if isinstance(section, dict):
                ordered.append((key, section))
        return ordered
    if isinstance(sections, list):
        result: list[tuple[str, dict[str, Any]]] = []
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            result.append((str(section.get("id") or f"section-{index + 1}"), section))
        return result
    return []


def _section_title(section_id: str, section: dict[str, Any]) -> str:
    return str(
        section.get("label")
        or section.get("title")
        or section.get("kicker")
        or section_id.replace("_", " ").title()
        or "章节"
    ).strip()


def render_report_markdown(report: dict[str, Any]) -> str:
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    document = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    bundled_markdown = str(document.get("markdown") or "").strip()
    if bundled_markdown:
        return bundled_markdown if bundled_markdown.endswith("\n") else f"{bundled_markdown}\n"

    title = str(document.get("title") or meta.get("title") or "职业发展报告").strip() or "职业发展报告"
    generated_at = str(meta.get("generated_at") or "--").strip() or "--"
    version = str(meta.get("version") or "--").strip() or "--"
    generation_mode = str(meta.get("generation_mode") or "--").strip() or "--"
    executive_summary = str(document.get("executive_summary") or meta.get("summary") or "系统已根据当前画像生成职业发展报告。").strip()

    lines = [
        f"# {title}",
        "",
        f"> 生成时间：{generated_at}",
        f"> 报告版本：{version}",
        f"> 生成模式：{generation_mode}",
        "",
        "## 执行摘要",
        executive_summary,
        "",
    ]

    for section_id, section in _iter_document_sections(report):
        heading = _section_title(section_id, section)
        markdown = str(section.get("markdown") or "").strip()
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        if markdown:
            lines.extend([f"## {heading}", "", markdown, ""])
            continue
        summary = str(
            data.get("summary")
            or data.get("industry_summary")
            or data.get("user_intent_summary")
            or ""
        ).strip()
        if summary:
            lines.extend([f"## {heading}", "", summary, ""])

    return "\n".join(lines).strip() + "\n"


def _render_markdown_html(markdown_text: str) -> str:
    import bleach
    import markdown

    def allow_attribute(tag, name, value):
        if tag == "a":
            return name in {"href", "title"}
        if tag == "img":
            if name in {"alt", "title"}:
                return True
            # 导出只能读取报告图片目录，不能加载远程图片或任意本机文件。
            return name == "src" and bool(re.fullmatch(r"/static/img/report/[\w.-]+", value))
        return False

    body = markdown.markdown(str(markdown_text or ""), extensions=["tables", "fenced_code", "sane_lists"])
    return bleach.clean(body, tags={
        "p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em",
        "blockquote", "pre", "code", "table", "thead", "tbody", "tr", "th", "td", "hr", "br", "a", "img",
    }, attributes=allow_attribute, protocols={"http", "https", "mailto"}, strip=True)


def render_markdown_export_html(markdown_text: str, *, title: str = "职业发展报告") -> str:
    body = _render_markdown_html(markdown_for_user_reading(markdown_text))
    safe_title = escape(title or "职业发展报告")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --panel: #ffffff;
      --line: #d9e2ef;
      --copy: #0f172a;
      --muted: #475569;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--copy);
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .page {{
      max-width: 960px;
      margin: 0 auto;
      padding: 32px 18px 56px;
    }}
    .paper {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 24px 48px rgba(15, 23, 42, 0.06);
    }}
    h1, h2, h3 {{
      color: var(--copy);
      line-height: 1.2;
      margin: 1.25em 0 0.55em;
    }}
    h1 {{ margin-top: 0; font-size: 2rem; }}
    h2 {{ font-size: 1.35rem; border-top: 1px solid var(--line); padding-top: 1rem; }}
    h3 {{ font-size: 1.05rem; }}
    p, li {{
      color: var(--muted);
      line-height: 1.8;
      font-size: 0.95rem;
    }}
    ul {{
      margin: 0.5rem 0 1rem;
      padding-left: 1.2rem;
    }}
  </style>
</head>
<body>
  <main class="page">
    <article class="paper">
      {body}
    </article>
  </main>
</body>
</html>
"""


def render_report_html(report: dict[str, Any]) -> str:
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    document = report.get("report_document") if isinstance(report.get("report_document"), dict) else {}
    bundled_html = str(document.get("html") or "").strip()
    if bundled_html:
        return bundled_html
    markdown_text = render_report_markdown(report)
    title = str(document.get("title") or meta.get("title") or "职业发展报告").strip() or "职业发展报告"
    return render_markdown_export_html(markdown_text, title=title)


def render_html_to_pdf_bytes(html_text: str) -> bytes:
    """将完整 HTML 转为 PDF。

    使用 PyMuPDF 的 Story 排版（项目已依赖 ``PyMuPDF`` / ``pymupdf``），无需单独安装 WeasyPrint。
    中文由 MuPDF 内置 CJK 回退字体排版，无需 Microsoft Word。
    """
    import io

    import pymupdf as fitz

    text = str(html_text or "").strip()
    if not text:
        raise ValueError("empty html for pdf export")
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)
    # Markdown 图片已限制为该目录下的文件名；Archive 不开放任意文件系统路径。
    text = text.replace('src="/static/img/report/', 'src="')
    archive = fitz.Archive(str(REPORT_IMAGE_DIR)) if REPORT_IMAGE_DIR.is_dir() else None
    story = fitz.Story(html=text, archive=archive)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    try:
        for _ in range(200):
            device = writer.begin_page(mediabox)
            more, filled = story.place(where)
            story.draw(device)
            writer.end_page()
            if not more:
                break
            if fitz.Rect(filled).is_empty:
                raise ValueError("报告中有无法分页的内容，请缩短过长的表格单元格或代码段后重试。")
        else:
            raise ValueError("报告超过 PDF 导出页数上限，请精简内容后重试。")
    finally:
        writer.close()
    return buf.getvalue()


def export_markdown_to_pdf_bytes(markdown_text: str, *, title: str = "职业发展报告") -> bytes:
    """Render the saved report directly, without DOCX conversion or an Office process."""
    cleaned = markdown_for_user_reading(markdown_text)
    if not cleaned:
        raise ValueError("报告正文为空，无法导出 PDF。")
    body = _render_markdown_html(cleaned)
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
    <title>{escape(title)}</title><style>
    body {{ font-family: sans-serif; font-size: 11pt; line-height: 1.6; color: #182335; }}
    h1 {{ font-size: 22pt; color: #163a53; margin: 0 0 18pt; }}
    h2 {{ font-size: 16pt; color: #163a53; margin: 18pt 0 9pt; }}
    h3, h4 {{ font-size: 12pt; margin: 12pt 0 6pt; }}
    p {{ margin: 6pt 0; }} ul, ol {{ margin: 6pt 0; padding-left: 20pt; }}
    blockquote {{ margin: 8pt 0 8pt 14pt; color: #475569; }}
    table {{ border-collapse: collapse; width: 100%; margin: 10pt 0; }}
    th, td {{ border: 0.6pt solid #cbd5e1; padding: 6pt; vertical-align: top; }}
    th {{ background-color: #edf3f8; font-weight: bold; }}
    pre {{ white-space: pre-wrap; padding: 9pt; background-color: #f1f5f9; font-size: 9pt; }}
    img {{ max-width: 100%; }} a {{ color: #17658b; }}
    </style></head><body>{body}</body></html>"""
    return render_html_to_pdf_bytes(html)


def export_markdown_to_docx_bytes(
    markdown_text: str,
    *,
    conda_env: str = DOCX_MCP_CONDA_ENV,
    title: str = "career-report",
) -> bytes:
    script = r"""
from pathlib import Path
import sys
from docx_mcp.document import DocxDocument
from docx_mcp.markdown import MarkdownConverter


def _paragraph_has_image(paragraph):
    for el in paragraph._element.iter():
        tag = el.tag if isinstance(el.tag, str) else str(el.tag)
        if tag.endswith("}drawing") or tag.endswith("drawing") or tag.endswith("}pict") or tag.endswith("pict"):
            return True
    return False


def _center_images_in_docx(path):
    try:
        from docx import Document as DocxPy
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        return
    try:
        doc = DocxPy(str(path))
        for p in doc.paragraphs:
            if _paragraph_has_image(p):
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        if _paragraph_has_image(p):
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc.save(str(path))
    except Exception:
        pass


md_path = Path(sys.argv[1])
docx_path = Path(sys.argv[2])
markdown = md_path.read_text(encoding="utf-8")
document = DocxDocument.create(str(docx_path))
MarkdownConverter.convert(document, markdown, base_dir=md_path.parent)
document.save(str(docx_path))
document.close()
_center_images_in_docx(docx_path)
"""
    safe_title = "".join(
        ch if ch.isalnum() or ch in {"-", "_", "."} else "-"
        for ch in str(title or "career-report")
    ).strip("-") or "career-report"
    python_exe = _resolve_docx_python(conda_env)
    with tempfile.TemporaryDirectory(prefix="career-report-docx-") as temp_dir:
        temp_path = Path(temp_dir)
        md_path = temp_path / "career-report.md"
        docx_path = temp_path / f"{safe_title}.docx"

        md_content = markdown_for_user_reading(markdown_text) or ""

        # 处理报告本地图片：把 /static/img/report/xxx 复制到临时目录并改写路径
        import re
        import shutil
        img_pattern = re.compile(r"!\[([^\]]*)\]\((/static/img/report/[^)]+)\)")
        for alt, img_path in img_pattern.findall(md_content):
            local_src = REPORT_IMAGE_DIR / img_path.removeprefix("/static/img/report/")
            if local_src.exists():
                dest = temp_path / local_src.name
                shutil.copy2(str(local_src), str(dest))
                md_content = md_content.replace(
                    f"![{alt}]({img_path})",
                    f"![{alt}](./{local_src.name})"
                )

        md_content = docx_prepare_markdown(md_content)
        md_path.write_text(md_content, encoding="utf-8")
        process = subprocess.run(
            [python_exe, "-c", script, str(md_path), str(docx_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
            timeout=180,
        )
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "").strip()
            raise RuntimeError(error or f"Docx_MCP export failed in conda env '{conda_env}'")
        if not docx_path.exists():
            raise RuntimeError("Docx_MCP did not produce a .docx file")
        return docx_path.read_bytes()
