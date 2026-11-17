"""进程内的 Markdown → Word 转换（python-docx）。

首选的转换器是外部解释器里的 docx_mcp（见 exporters.export_markdown_to_docx_bytes）。它不在依赖清单里，
全新环境往往没有，所以这里提供一个只依赖 requirements.txt 的兜底实现，保证报告始终能导出 Word。
排版（配色、字号、标题底色、提示块）由 docx_layout.format_report_docx 统一处理，这里只负责结构：
标题、段落、列表、表格、引用、代码块、图片和行内样式。
"""
import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

_INLINE = re.compile(r"(\*\*[^*\n]+?\*\*|__[^_\n]+?__|`[^`\n]+?`|\[[^\]\n]+?\]\([^)\s]+?\)|(?<![*\w])\*[^*\n]+?\*(?![*\w]))")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_IMAGE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)\)\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_SAFE_URL = re.compile(r"^https?://", re.IGNORECASE)
MAX_IMAGE_WIDTH = Cm(15)


def _add_hyperlink(paragraph, url, text):
    relation = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), relation)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "1F5FA8")
    properties.append(color)
    properties.append(underline)
    run.append(properties)
    content = OxmlElement("w:t")
    content.text = text
    content.set(qn("xml:space"), "preserve")
    run.append(content)
    link.append(run)
    paragraph._p.append(link)


def add_inline(paragraph, text):
    """行内样式：粗体、斜体、行内代码和链接；只有 http(s) 链接会变成超链接。"""
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith(("**", "__")) and part.endswith(part[:2]) and len(part) > 4:
            paragraph.add_run(part[2:-2]).bold = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Consolas")
        elif part.startswith("[") and "](" in part and part.endswith(")"):
            label, url = part[1:-1].split("](", 1)
            if _SAFE_URL.match(url):
                _add_hyperlink(paragraph, url, label)
            else:
                paragraph.add_run(label)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            paragraph.add_run(part[1:-1]).italic = True
        else:
            paragraph.add_run(part)


def _split_row(line):
    cells = line.strip()
    cells = cells[1:] if cells.startswith("|") else cells
    cells = cells[:-1] if cells.endswith("|") else cells
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", cells)]


def _add_table(document, rows):
    width = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    for row_index, row in enumerate(rows):
        for column in range(width):
            cell = table.cell(row_index, column)
            text = row[column].replace("\\|", "|") if column < len(row) else ""
            paragraph = cell.paragraphs[0]
            add_inline(paragraph, text)
            if row_index == 0:
                for run in paragraph.runs:
                    run.bold = True
    document.add_paragraph()


def _add_image(document, alt, source, base_dir):
    path = (Path(base_dir) / source).resolve() if base_dir else None
    # 只嵌入报告目录内的本地图片，不抓取远程地址，也不读取目录之外的文件。
    if path and path.is_file() and Path(base_dir).resolve() in path.parents:
        try:
            document.add_picture(str(path), width=MAX_IMAGE_WIDTH)
            document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            return
        except Exception:
            pass
    if alt:
        document.add_paragraph(f"[图片：{alt}]")


def convert_markdown_to_docx(markdown_text, docx_path, base_dir=None):
    document = Document()
    lines = str(markdown_text or "").replace("\r\n", "\n").split("\n")
    index, in_code, code = 0, False, []
    while index < len(lines):
        line = lines[index]
        index += 1
        if line.strip().startswith("```"):
            if in_code:
                paragraph = document.add_paragraph()
                run = paragraph.add_run("\n".join(code))
                run.font.name = "Consolas"
                run.font.size = Pt(9)
                code, in_code = [], False
            else:
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        if not line.strip():
            continue
        if line.lstrip().startswith("|") and index < len(lines) and _TABLE_SEPARATOR.match(lines[index]):
            rows = [_split_row(line)]
            index += 1
            while index < len(lines) and lines[index].lstrip().startswith("|"):
                rows.append(_split_row(lines[index]))
                index += 1
            _add_table(document, rows)
            continue
        heading = _HEADING.match(line)
        if heading:
            paragraph = document.add_paragraph(style=f"Heading {len(heading.group(1))}")
            add_inline(paragraph, heading.group(2))
            continue
        if _RULE.match(line):
            continue
        image = _IMAGE.match(line)
        if image:
            _add_image(document, image.group(1), image.group(2), base_dir)
            continue
        bullet, ordered = _BULLET.match(line), _ORDERED.match(line)
        if bullet or ordered:
            match = bullet or ordered
            level = 2 if len(match.group(1).replace("\t", "    ")) >= 2 else 1
            name = "List Bullet" if bullet else "List Number"
            paragraph = document.add_paragraph(style=name if level == 1 else f"{name} 2")
            add_inline(paragraph, match.group(2))
            continue
        if line.lstrip().startswith(">"):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Cm(0.8)
            add_inline(paragraph, re.sub(r"^\s*>+\s?", "", line))
            for run in paragraph.runs:
                run.italic = True
                run.font.color.rgb = RGBColor(0x52, 0x69, 0x80)
            continue
        add_inline(document.add_paragraph(), line.strip())
    if in_code and code:
        document.add_paragraph("\n".join(code)).runs[0].font.name = "Consolas"
    document.save(str(docx_path))
