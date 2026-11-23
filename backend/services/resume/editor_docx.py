"""Editable A4 Word (.docx) resume export matching the PDF layout and Markdown formatting."""
import base64
from io import BytesIO
import re
from urllib.parse import urlsplit

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .editor_document import INLINE_MARKDOWN, WORK_TITLES

ACCENT_HEX = {"classic": "1E2126", "blue": "004A91", "compact": "1E3A5F"}
RULE_HEX = "97A1AC"
LATIN_FONT = "Times New Roman"
CJK_FONT = "Noto Serif SC"
CJK_HEADING_FONT = "Noto Sans SC"
INK = RGBColor(0x1E, 0x21, 0x26)
STRONG_INK = RGBColor(0x1E, 0x21, 0x26)
MUTED = RGBColor(0x50, 0x54, 0x5A)
LINK_HEX = "004A91"
LINK_COLOR = RGBColor(0x00, 0x4A, 0x91)


def _hex_rgb(code):
    return RGBColor(int(code[0:2], 16), int(code[2:4], 16), int(code[4:6], 16))


def _set_run_font(run, size_pt, *, bold=False, italic=False, strike=False, color=INK, cjk_font=CJK_FONT):
    run.font.name = LATIN_FONT
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.italic = italic
    run.font.strike = strike
    run.font.color.rgb = color
    r_pr = run._r.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, r_fonts)
    r_fonts.set(qn("w:ascii"), LATIN_FONT)
    r_fonts.set(qn("w:hAnsi"), LATIN_FONT)
    r_fonts.set(qn("w:eastAsia"), cjk_font)


def _add_hyperlink(paragraph, label, url, size_pt, *, bold=False):
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    r_fonts = OxmlElement("w:rFonts")
    r_fonts.set(qn("w:ascii"), LATIN_FONT)
    r_fonts.set(qn("w:hAnsi"), LATIN_FONT)
    r_fonts.set(qn("w:eastAsia"), CJK_FONT)
    r_pr.append(r_fonts)
    if bold:
        r_pr.append(OxmlElement("w:b"))
    color = OxmlElement("w:color")
    color.set(qn("w:val"), LINK_HEX)
    r_pr.append(color)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(round(size_pt * 2))))
    r_pr.append(sz)
    sz_cs = OxmlElement("w:szCs")
    sz_cs.set(qn("w:val"), str(int(round(size_pt * 2))))
    r_pr.append(sz_cs)
    new_run.append(r_pr)

    text_el = OxmlElement("w:t")
    text_el.set(qn("xml:space"), "preserve")
    text_el.text = label
    new_run.append(text_el)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def _append_inline_markdown(paragraph, text, size_pt, *, base_bold=False, color=INK):
    offset = 0
    for match in INLINE_MARKDOWN.finditer(text):
        if match.start() > offset:
            run = paragraph.add_run(text[offset:match.start()])
            _set_run_font(run, size_pt, bold=base_bold, color=STRONG_INK if base_bold else color)
        label, url, marker, inner = match.groups()
        if url:
            try:
                target = urlsplit(url)
                allowed = bool(target.hostname and not target.username and not target.password)
            except ValueError:
                allowed = False
            if allowed:
                _add_hyperlink(paragraph, label, url, size_pt, bold=base_bold)
            else:
                run = paragraph.add_run(match.group())
                _set_run_font(run, size_pt, bold=base_bold, color=color)
        else:
            is_bold = base_bold or marker == "**"
            run = paragraph.add_run(inner)
            _set_run_font(
                run,
                size_pt,
                bold=is_bold,
                italic=(marker == "*"),
                strike=(marker == "~~"),
                color=STRONG_INK if is_bold else color,
            )
        offset = match.end()
    if offset < len(text):
        run = paragraph.add_run(text[offset:])
        _set_run_font(run, size_pt, bold=base_bold, color=STRONG_INK if base_bold else color)


def _clear_table_borders(table):
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "none")
        borders.append(el)
    tbl_pr.append(borders)


def _set_table_column_widths(table, widths_mm):
    """Explicitly write tblW, fixed tblLayout, tblGrid gridCols, and tcW so Word & WPS honor exact column widths."""
    dxa_widths = [int(round(w * 56.6929)) for w in widths_mm]
    total_dxa = sum(dxa_widths)
    tbl = table._tbl
    tbl_pr = tbl.tblPr

    for tag in ("w:tblW", "w:tblLayout"):
        existing = tbl_pr.find(qn(tag))
        if existing is not None:
            tbl_pr.remove(existing)

    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:w"), str(total_dxa))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_pr.append(tbl_w)

    tbl_layout = OxmlElement("w:tblLayout")
    tbl_layout.set(qn("w:type"), "fixed")
    tbl_pr.append(tbl_layout)

    old_grid = tbl.find(qn("w:tblGrid"))
    if old_grid is not None:
        tbl.remove(old_grid)
    new_grid = OxmlElement("w:tblGrid")
    for dxa in dxa_widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(dxa))
        new_grid.append(col)
    tbl_pr.addnext(new_grid)

    for row in table.rows:
        for cell, w_mm, dxa in zip(row.cells, widths_mm, dxa_widths):
            cell.width = Mm(w_mm)
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.insert(0, tc_w)
            tc_w.set(qn("w:w"), str(dxa))
            tc_w.set(qn("w:type"), "dxa")


def _set_cell_margins(cell, *, top=0, bottom=0, left=0, right=40):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = OxmlElement("w:tcMar")
    for side, val in (("top", top), ("bottom", bottom), ("left", left), ("right", right)):
        node = OxmlElement(f"w:{side}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        tc_mar.append(node)
    tc_pr.append(tc_mar)


def _set_bottom_border(paragraph, color_hex):
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "2")
    bottom.set(qn("w:color"), color_hex)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def _set_paragraph_spacing(paragraph, *, before=0, after=1.5, line_spacing=1.22):
    fmt = paragraph.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line_spacing


def render_docx(document):
    compact = document.get("layout") == "compact"
    accent_hex = ACCENT_HEX.get(document.get("style", "classic"), ACCENT_HEX["classic"])
    accent_rgb = _hex_rgb(accent_hex)
    font_scale = max(0.85, min(1.18, float(document.get("font_scale") or 1.0)))
    body_size = round((9.0 if compact else 9.5) * font_scale, 2)
    line_gap = 1.18 if compact else 1.24

    doc = Document()
    page = doc.sections[0]
    page.page_width = Mm(210)
    page.page_height = Mm(297)
    page.top_margin = Mm(10 if compact else 12)
    page.bottom_margin = Mm(10 if compact else 12)
    page.left_margin = Mm(12.5)
    page.right_margin = Mm(12.5)
    usable_width_mm = 210 - 25  # 185 mm

    normal = doc.styles["Normal"]
    normal.font.name = LATIN_FONT
    normal.font.size = Pt(body_size)
    normal.font.color.rgb = INK

    contact = document["contact"]
    extras_raw = list(document.get("extras") or [])
    schedule = next((item["value"] for item in extras_raw if item["label"] == "实习安排"), "")

    # Header masthead
    show_photo = document.get("show_photo", True) is not False
    has_visible_photo = bool(document.get("photo")) and show_photo
    if contact.get("target") or has_visible_photo:
        head_tbl = doc.add_table(rows=1, cols=3)
        head_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        head_tbl.autofit = False
        _clear_table_borders(head_tbl)
        widths = (usable_width_mm * 0.42, usable_width_mm * 0.32, usable_width_mm * 0.26)
        _set_table_column_widths(head_tbl, widths)
        for cell in head_tbl.rows[0].cells:
            _set_cell_margins(cell, right=40)

        left_cell, mid_cell, right_cell = head_tbl.rows[0].cells
        if contact.get("target"):
            p = left_cell.paragraphs[0]
            _set_paragraph_spacing(p, before=0, after=0.5, line_spacing=1.15)
            _set_run_font(p.add_run("求职意向"), 9.2, bold=True, color=accent_rgb)
            p2 = left_cell.add_paragraph()
            _set_paragraph_spacing(p2, before=0, after=0.5, line_spacing=1.15)
            _set_run_font(p2.add_run(contact["target"]), 8.6, color=INK)
            if schedule:
                p3 = left_cell.add_paragraph()
                _set_paragraph_spacing(p3, before=0, after=0, line_spacing=1.15)
                _set_run_font(p3.add_run(schedule), 8.2, color=MUTED)
        else:
            left_cell.paragraphs[0].text = ""

        p_name = mid_cell.paragraphs[0]
        p_name.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_paragraph_spacing(p_name, before=0, after=2, line_spacing=1.1)
        _set_run_font(p_name.add_run(contact.get("name") or document["title"]), 20, bold=True, color=accent_rgb)

        p_photo = right_cell.paragraphs[0]
        p_photo.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _set_paragraph_spacing(p_photo, before=0, after=0, line_spacing=1.0)
        if has_visible_photo:
            img_stream = BytesIO(base64.b64decode(document["photo"]))
            p_photo.add_run().add_picture(img_stream, width=Mm(17))
    else:
        p_name = doc.add_paragraph()
        p_name.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_paragraph_spacing(p_name, before=0, after=3, line_spacing=1.1)
        _set_run_font(p_name.add_run(contact.get("name") or document["title"]), 20, bold=True, color=accent_rgb)

    # Contact line
    extra_items = [item for item in extras_raw if item.get("value") and (item.get("label") != "实习安排" or not contact.get("target"))]
    channels = []
    if contact.get("phone"):
        channels.append(("text", contact["phone"]))
    if contact.get("email"):
        channels.append(("text", contact["email"]))
    if extra_items:
        first = extra_items.pop(0)
        url = first["value"]
        if first["label"] in {"GitHub", "个人主页"} and re.fullmatch(r"https?://[^\s()]+", url):
            channels.append(("link", (url.split("://", 1)[1], url)))
        else:
            channels.append(("text", f'{first["label"]}：{url}' if first["label"] else url))

    if channels:
        c_tbl = doc.add_table(rows=1, cols=len(channels))
        c_tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        c_tbl.autofit = False
        _clear_table_borders(c_tbl)
        ratios = (0.33, 0.30, 0.37) if len(channels) == 3 else [1 / len(channels)] * len(channels)
        _set_table_column_widths(c_tbl, [usable_width_mm * r for r in ratios])
        for idx, (cell, (kind, val)) in enumerate(zip(c_tbl.rows[0].cells, channels)):
            _set_cell_margins(cell, top=30, bottom=30, left=0, right=0)
            p = cell.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if len(channels) == 1 else (
                WD_ALIGN_PARAGRAPH.RIGHT if idx == len(channels) - 1 and len(channels) > 1 else WD_ALIGN_PARAGRAPH.LEFT
            )
            _set_paragraph_spacing(p, before=1, after=2, line_spacing=1.1)
            if kind == "link":
                _add_hyperlink(p, val[0], val[1], 8.6)
            else:
                _set_run_font(p.add_run(val), 8.6, color=MUTED)

    if extra_items:
        p_ext = doc.add_paragraph()
        _set_paragraph_spacing(p_ext, before=0, after=2, line_spacing=1.15)
        for idx, item in enumerate(extra_items):
            if idx:
                _set_run_font(p_ext.add_run("  ·  "), 8.6, color=MUTED)
            url = item["value"]
            if item["label"] in {"GitHub", "个人主页"} and re.fullmatch(r"https?://[^\s()]+", url):
                _add_hyperlink(p_ext, url.split("://", 1)[1], url, 8.6)
            else:
                text = f'{item["label"]}：{url}' if item["label"] else url
                _set_run_font(p_ext.add_run(text), 8.6, color=MUTED)

    # Sections
    for section in document["sections"]:
        if not section["content"]:
            continue
        title = section["title"]
        is_project = title in {"项目经历", "项目经验"}
        is_work = title in WORK_TITLES
        is_edu = title in {"教育经历", "教育背景"}

        h_p = doc.add_paragraph()
        _set_paragraph_spacing(h_p, before=5.5 if compact else 7.5, after=3.0, line_spacing=1.15)
        h_p.paragraph_format.keep_with_next = True
        _set_bottom_border(h_p, RULE_HEX if document.get("style", "classic") == "classic" else accent_hex)
        _set_run_font(h_p.add_run(title), 11.2, bold=True, color=accent_rgb, cjk_font=CJK_HEADING_FONT)

        prev_blank = False
        for raw in section["content"].splitlines():
            line = raw.strip()
            if not line:
                prev_blank = True
                continue
            gap_before = (4.0 if compact else 5.5) if (is_project or is_work) and prev_blank else 0
            prev_blank = False

            cols = [cell.strip() for cell in re.split(r"[|｜]", line)]
            if title == "获奖情况" and len(cols) == 2 and all(col.startswith("- ") for col in cols):
                tbl = doc.add_table(rows=1, cols=2)
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                tbl.autofit = False
                _clear_table_borders(tbl)
                _set_table_column_widths(tbl, [usable_width_mm * r for r in (0.52, 0.48)])
                for cell, col in zip(tbl.rows[0].cells, cols):
                    _set_cell_margins(cell, top=10, bottom=15, left=0, right=40)
                    p = cell.paragraphs[0]
                    _set_paragraph_spacing(p, before=0, after=0.5, line_spacing=1.15)
                    _set_run_font(p.add_run("• "), 8.6, color=MUTED)
                    _append_inline_markdown(p, col[2:], 8.8)
            elif (is_project or is_work or is_edu) and len(cols) == 3 and all(cols) and not re.match(r"^[-*•]|^\d+\.", line):
                tbl = doc.add_table(rows=1, cols=3)
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                tbl.autofit = False
                _clear_table_borders(tbl)
                ratios = (0.65, 0.15, 0.20) if is_project else (0.54, 0.26, 0.20) if is_work else (0.36, 0.43, 0.21)
                _set_table_column_widths(tbl, [usable_width_mm * r for r in ratios])
                for idx, (cell, val) in enumerate(zip(tbl.rows[0].cells, cols)):
                    _set_cell_margins(cell, top=int(gap_before * 20), bottom=20, left=0, right=40 if idx < 2 else 0)
                    p = cell.paragraphs[0]
                    p.paragraph_format.keep_with_next = True
                    _set_paragraph_spacing(p, before=0, after=0.8, line_spacing=1.15)
                    if idx == 0:
                        _append_inline_markdown(p, val, 9.6, base_bold=True, color=STRONG_INK)
                    elif idx == 1:
                        if is_project:
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        _append_inline_markdown(p, val, 8.7, color=MUTED)
                    else:
                        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                        _append_inline_markdown(p, val, 8.7, color=MUTED)
            elif re.match(r"^#{1,6}\s+", line):
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, before=gap_before or 2.5, after=1.0, line_spacing=1.15)
                p.paragraph_format.keep_with_next = True
                _append_inline_markdown(p, line.lstrip("#").strip(), 9.5, base_bold=True, color=STRONG_INK)
            elif re.match(r"^[-*•]\s+", line):
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, before=gap_before, after=1.2 if compact else 1.8, line_spacing=line_gap)
                p.paragraph_format.left_indent = Pt(9.5)
                p.paragraph_format.first_line_indent = Pt(-9.5)
                _set_run_font(p.add_run("• "), 8.6, color=MUTED)
                _append_inline_markdown(p, line[1:].lstrip(), body_size)
            else:
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, before=gap_before, after=1.0 if compact else 1.5, line_spacing=line_gap)
                _append_inline_markdown(p, line, body_size)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def _set_paragraph_bar_style(paragraph, fill_hex, border_hex):
    p_pr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    p_pr.append(shd)
    p_bdr = OxmlElement("w:pBdr")
    left = OxmlElement("w:left")
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")
    left.set(qn("w:space"), "6")
    left.set(qn("w:color"), border_hex)
    p_bdr.append(left)
    for side in ("top", "bottom", "right"):
        edge = OxmlElement(f"w:{side}")
        edge.set(qn("w:val"), "single")
        edge.set(qn("w:sz"), "4")
        edge.set(qn("w:space"), "3")
        edge.set(qn("w:color"), fill_hex)
        p_bdr.append(edge)
    p_pr.append(p_bdr)


def _append_html_inline(paragraph, node, size_pt, *, bold=False, italic=False, color=INK):
    if node.text:
        text = re.sub(r"\s+", " ", node.text)
        if text:
            _set_run_font(paragraph.add_run(text), size_pt, bold=bold, italic=italic, color=STRONG_INK if bold else color)
    for child in node:
        tag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
        if tag == "br":
            paragraph.add_run().add_break()
        elif tag in ("strong", "b"):
            _append_html_inline(paragraph, child, size_pt, bold=True, italic=italic, color=STRONG_INK)
        elif tag in ("em", "i"):
            _append_html_inline(paragraph, child, size_pt, bold=bold, italic=True, color=color)
        elif tag == "a":
            href = (child.get("href") or "").strip()
            label = "".join(child.itertext()).strip()
            if label and re.match(r"^https?://", href, re.I):
                _add_hyperlink(paragraph, label, href, size_pt, bold=bold)
            elif label:
                _set_run_font(paragraph.add_run(label), size_pt, bold=bold, color=LINK_COLOR)
        elif tag in ("span", "code", "small"):
            cls = (child.get("class") or "").lower()
            c_color = MUTED if "sub" in cls or "date" in cls else color
            _append_html_inline(paragraph, child, size_pt - 0.4 if "sub" in cls else size_pt, bold=bold, italic=italic, color=c_color)
        else:
            _append_html_inline(paragraph, child, size_pt, bold=bold, italic=italic, color=color)
        if child.tail:
            tail = re.sub(r"\s+", " ", child.tail)
            if tail:
                _set_run_font(paragraph.add_run(tail), size_pt, bold=bold, italic=italic, color=STRONG_INK if bold else color)


def render_html_to_docx(html_text):
    """Convert generated Skill HTML resume into a clean, styled, editable Word (.docx) document."""
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(html_text)
    body_nodes = tree.xpath("//div[contains(concat(' ', normalize-space(@class), ' '), ' page ')]")
    root = body_nodes[0] if body_nodes else (tree.find(".//body") or tree)

    doc = Document()
    page = doc.sections[0]
    page.page_width = Mm(210)
    page.page_height = Mm(297)
    page.top_margin = Mm(11)
    page.bottom_margin = Mm(11)
    page.left_margin = Mm(13)
    page.right_margin = Mm(13)
    usable_mm = 184

    normal = doc.styles["Normal"]
    normal.font.name = LATIN_FONT
    normal.font.size = Pt(9.2)
    normal.font.color.rgb = INK

    blue_rgb = RGBColor(0x1D, 0x4E, 0xD8)

    def render_node(el):
        if not isinstance(el.tag, str):
            return
        tag = el.tag.lower()
        cls = set((el.get("class") or "").lower().split())
        if tag in ("style", "script", "head", "meta", "title", "link"):
            return

        if "hero" in cls:
            imgs = el.xpath(".//img[@src]")
            photo_data = None
            for img in imgs:
                src = img.get("src") or ""
                if src.startswith("data:image/") and ";base64," in src:
                    try:
                        photo_data = base64.b64decode(src.split(";base64,", 1)[1])
                    except Exception:
                        photo_data = None
                    break
            if photo_data:
                tbl = doc.add_table(rows=1, cols=2)
                tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                tbl.autofit = False
                _clear_table_borders(tbl)
                left_c, right_c = tbl.rows[0].cells
                left_c.width = Mm(usable_mm - 24)
                right_c.width = Mm(24)
                _set_cell_margins(left_c, right=60)
                _set_cell_margins(right_c, right=0)
                first_p = True
                for child in el.iter():
                    if child is el or not isinstance(child.tag, str):
                        continue
                    ctag = child.tag.lower()
                    ccls = set((child.get("class") or "").lower().split())
                    if ctag == "h1":
                        p = left_c.paragraphs[0] if first_p else left_c.add_paragraph()
                        first_p = False
                        _set_paragraph_spacing(p, before=0, after=2, line_spacing=1.1)
                        _set_run_font(p.add_run("".join(child.itertext()).strip()), 19, bold=True, color=STRONG_INK)
                    elif "tagline" in ccls:
                        p = left_c.paragraphs[0] if first_p else left_c.add_paragraph()
                        first_p = False
                        _set_paragraph_spacing(p, before=0, after=2, line_spacing=1.15)
                        _set_run_font(p.add_run("".join(child.itertext()).strip()), 9.8, bold=True, color=blue_rgb)
                    elif "meta" in ccls:
                        p = left_c.paragraphs[0] if first_p else left_c.add_paragraph()
                        first_p = False
                        _set_paragraph_spacing(p, before=0, after=1.5, line_spacing=1.15)
                        _append_html_inline(p, child, 8.6, color=MUTED)
                p_img = right_c.paragraphs[0]
                p_img.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                _set_paragraph_spacing(p_img, before=0, after=0, line_spacing=1.0)
                p_img.add_run().add_picture(BytesIO(photo_data), width=Mm(18))
                return
            for child in el:
                render_node(child)
            return

        if tag == "h1":
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, before=0, after=2, line_spacing=1.1)
            _set_run_font(p.add_run("".join(el.itertext()).strip()), 19, bold=True, color=STRONG_INK)
            return

        if tag == "h2":
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, before=7, after=3, line_spacing=1.15)
            p.paragraph_format.keep_with_next = True
            _set_bottom_border(p, "93C5FD")
            _set_run_font(p.add_run("".join(el.itertext()).strip()), 10.8, bold=True, color=blue_rgb)
            return

        if tag == "h3":
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, before=4, after=1.5, line_spacing=1.15)
            p.paragraph_format.keep_with_next = True
            _append_html_inline(p, el, 9.6, bold=True, color=STRONG_INK)
            return

        if "tagline" in cls:
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, before=0, after=2.5, line_spacing=1.15)
            _set_run_font(p.add_run("".join(el.itertext()).strip()), 9.8, bold=True, color=blue_rgb)
            return

        if "bar" in cls:
            fill, border = ("FEF2F2", "DC2626") if "red" in cls else ("ECFDF5", "059669") if "green" in cls else ("EFF6FF", "2563EB")
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, before=4.5, after=2.5, line_spacing=1.2)
            p.paragraph_format.keep_with_next = True
            _set_paragraph_bar_style(p, fill, border)
            _append_html_inline(p, el, 9.4, bold=True, color=STRONG_INK)
            return

        if "tags" in cls:
            tags = ["".join(t.itertext()).strip() for t in el if isinstance(t.tag, str) and "".join(t.itertext()).strip()]
            if tags:
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, before=1.5, after=2.5, line_spacing=1.2)
                _set_run_font(p.add_run("技术关键词："), 8.6, bold=True, color=STRONG_INK)
                _set_run_font(p.add_run(" / ".join(tags)), 8.6, color=RGBColor(0x1E, 0x3A, 0x8A))
            return

        if tag in ("ul", "ol"):
            for idx, li in enumerate(el, 1):
                if not isinstance(li.tag, str) or li.tag.lower() != "li":
                    continue
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, before=0, after=1.5, line_spacing=1.2)
                p.paragraph_format.left_indent = Pt(10)
                p.paragraph_format.first_line_indent = Pt(-10)
                prefix = f"{idx}. " if tag == "ol" else "• "
                _set_run_font(p.add_run(prefix), 8.6, color=MUTED)
                _append_html_inline(p, li, 9.1)
            return

        if tag in ("p",) or "kv" in cls or "meta" in cls:
            if "".join(el.itertext()).strip():
                p = doc.add_paragraph()
                _set_paragraph_spacing(p, before=0, after=1.8, line_spacing=1.2)
                _append_html_inline(p, el, 8.7 if "meta" in cls else 9.1, color=MUTED if "meta" in cls else INK)
            return

        if tag == "table":
            rows = el.xpath(".//tr")
            if rows:
                max_cols = max((len(r.xpath("./td|./th")) for r in rows), default=0)
                if max_cols:
                    tbl = doc.add_table(rows=len(rows), cols=max_cols)
                    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
                    _clear_table_borders(tbl)
                    for r_idx, tr in enumerate(rows):
                        cells = tr.xpath("./td|./th")
                        for c_idx, td in enumerate(cells):
                            cell = tbl.rows[r_idx].cells[c_idx]
                            _set_cell_margins(cell, top=15, bottom=15, left=0, right=40)
                            p = cell.paragraphs[0]
                            _set_paragraph_spacing(p, before=0, after=0.8, line_spacing=1.18)
                            _append_html_inline(p, td, 8.9, bold=(td.tag.lower() == "th"))
            return

        # Container elements (div, section, main, article, etc.)
        has_block_child = any(isinstance(c.tag, str) and c.tag.lower() in ("div", "section", "h1", "h2", "h3", "p", "ul", "ol", "table", "header", "article") for c in el)
        if has_block_child:
            for child in el:
                render_node(child)
        elif "".join(el.itertext()).strip():
            p = doc.add_paragraph()
            _set_paragraph_spacing(p, before=0, after=1.5, line_spacing=1.2)
            _append_html_inline(p, el, 9.1)

    for child in root:
        render_node(child)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
