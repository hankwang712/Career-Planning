"""Reading roles distilled from Career_Report_Enhanced_Layout.docx.

The original reference remains untouched; this styles newly exported reports.
"""
import re


NOTE_STYLES = [
    (r"^问题[：:]", "B64732", "FFF4F1"),
    (r"^(?:改进方式|突出建议|这项优势还没有表达充分)[：:]", "087E65", "F0FAF6"),
    (r"^(?:基于已有事实的改写|改写示例)[：:]", "4265AD", "F1F5FF"),
    (r"^(?:还需补充|待确认|后续仍需确认|仍需核实的材料|进入条件|复核与调整)[：:]", "9B6F26", "FFF9ED"),
    (r"^(?:原文依据|原文)[：:]", "6E7C8E", "F5F7FA"),
]


def format_report_docx(path):
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    doc = Document(str(path))
    # The Markdown converter may emit no section properties; create the page definition.
    doc._element.body.get_or_add_sectPr()
    normal = doc.styles["Normal"]
    # The converter omits list starts; WPS then renders decimal lists from zero.
    for level in doc.part.numbering_part.element.findall(".//" + qn("w:lvl")):
        form = level.find(qn("w:numFmt"))
        if form is not None and form.get(qn("w:val")) != "bullet" and level.find(qn("w:start")) is None:
            start = OxmlElement("w:start")
            start.set(qn("w:val"), "1")
            level.insert(0, start)

    def font(style, size, color, bold=False):
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(color)
        style.font.bold = bold
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    def shade(paragraph, fill):
        props = paragraph._p.get_or_add_pPr()
        node = props.find(qn("w:shd"))
        if node is None:
            node = OxmlElement("w:shd")
            props.append(node)
        node.set(qn("w:val"), "clear")
        node.set(qn("w:fill"), fill)

    def recolor(paragraph, color, size=None):
        # Keep runs, links, numbering and bookmarks intact.
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor.from_string(color)
            if size:
                run.font.size = Pt(size)

    font(normal, 10.5, "25364D")
    normal.paragraph_format.line_spacing = 1.5
    normal.paragraph_format.space_after = Pt(8)
    for name, size, color in [("Title", 21, "16263C"), ("Heading 1", 14.5, "FFFFFF"),
                              ("Heading 2", 12, "165C76"), ("Heading 3", 10.5, "17355D"),
                              ("Heading 4", 10.5, "526980")]:
        try:
            style = doc.styles[name]
        except KeyError:
            style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
            style.base_style = normal
        font(style, size, color, True)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(18 if name == "Heading 2" else 12)
        style.paragraph_format.space_after = Pt(10)
        if name.startswith("Heading"):
            props = style.element.get_or_add_pPr()
            outline = props.find(qn("w:outlineLvl"))
            if outline is None:
                outline = OxmlElement("w:outlineLvl")
                props.append(outline)
            outline.set(qn("w:val"), str(int(name[-1]) - 1))
    for section in doc.sections:
        section.page_width, section.page_height = Mm(210), Mm(297)
        section.top_margin = section.bottom_margin = Mm(16)
        section.left_margin = section.right_margin = Mm(24)
        section.header_distance = section.footer_distance = Mm(8)
        footer = section.footer.paragraphs[0]
        if not footer.text and not footer._p.xpath(".//w:fldChar"):
            footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            run = footer.add_run()
            field = OxmlElement("w:fldSimple")
            field.set(qn("w:instr"), "PAGE")
            run._r.addnext(field)

    conclusion = False
    for index, paragraph in enumerate(doc.paragraphs):
        text = paragraph.text.strip()
        name = paragraph.style.name.lower()
        if paragraph._p.xpath(".//w:drawing | .//w:pict"):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            continue
        if index == 0 and name.startswith(("heading", "title")):
            paragraph.style = doc.styles["Title"]
            recolor(paragraph, "16263C", 21)
            continue
        if name == "heading 2":
            paragraph.style = doc.styles["Heading 1"]
            conclusion = "核心结论" in text
            shade(paragraph, "17355D")
            recolor(paragraph, "FFFFFF", 14.5)
            paragraph.paragraph_format.left_indent = Mm(3)
            paragraph.paragraph_format.line_spacing = 1.65
            continue
        if name.startswith("heading"):
            if name == "heading 3":
                paragraph.style = doc.styles["Heading 2"]
            elif name == "heading 4":
                paragraph.style = doc.styles["Heading 3"]
            color = "165C76" if name == "heading 3" else "526980"
            recolor(paragraph, color)
            continue
        paragraph.paragraph_format.line_spacing = 1.5
        paragraph.paragraph_format.space_after = Pt(8)
        paragraph.paragraph_format.widow_control = True
        if conclusion and text:
            shade(paragraph, "F0F5FD")
            recolor(paragraph, "1C548D")
        else:
            for pattern, color, fill in NOTE_STYLES:
                if re.match(pattern, text):
                    shade(paragraph, fill)
                    recolor(paragraph, color, 9.5 if "原文" in pattern else None)
                    paragraph.paragraph_format.space_before = Pt(5)
                    paragraph.paragraph_format.left_indent = Mm(3)
                    paragraph.paragraph_format.right_indent = Mm(3)
                    break
            if re.match(r"^(?:交付物|完成标准|验收要点|对应要求|岗位要求|对照判断)[：:]", text):
                recolor(paragraph, "1B5B8B")
            if re.match(r"^(?:来源|地点)[：:]", text):
                recolor(paragraph, "667B90", 9)
    doc.save(str(path))
