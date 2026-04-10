from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path
from typing import Any


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
    lines = str(markdown_text or "").splitlines()
    html: list[str] = []
    in_list = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                html.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("# "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h1>{escape(stripped[2:].strip())}</h1>")
            continue
        if stripped.startswith("## "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h2>{escape(stripped[3:].strip())}</h2>")
            continue
        if stripped.startswith("### "):
            if in_list:
                html.append("</ul>")
                in_list = False
            html.append(f"<h3>{escape(stripped[4:].strip())}</h3>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{escape(stripped[2:].strip())}</li>")
            continue
        if in_list:
            html.append("</ul>")
            in_list = False
        html.append(f"<p>{escape(stripped)}</p>")
    if in_list:
        html.append("</ul>")
    return "\n".join(html)


def render_markdown_export_html(markdown_text: str, *, title: str = "职业发展报告") -> str:
    body = _render_markdown_html(markdown_text)
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


def export_markdown_to_docx_bytes(
    markdown_text: str,
    *,
    conda_env: str = DOCX_MCP_CONDA_ENV,
    title: str = "career-report",
) -> bytes:
    script = """
from pathlib import Path
import sys
from docx_mcp.document import DocxDocument
from docx_mcp.markdown import MarkdownConverter

md_path = Path(sys.argv[1])
docx_path = Path(sys.argv[2])
markdown = md_path.read_text(encoding='utf-8')
document = DocxDocument.create(str(docx_path))
MarkdownConverter.convert(document, markdown, base_dir=md_path.parent)
document.save(str(docx_path))
document.close()
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
        md_path.write_text(markdown_text or "", encoding="utf-8")
        process = subprocess.run(
            [python_exe, "-c", script, str(md_path), str(docx_path)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if process.returncode != 0:
            error = (process.stderr or process.stdout or "").strip()
            raise RuntimeError(error or f"Docx_MCP export failed in conda env '{conda_env}'")
        if not docx_path.exists():
            raise RuntimeError("Docx_MCP did not produce a .docx file")
        return docx_path.read_bytes()
