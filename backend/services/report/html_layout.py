"""Semantic export layout used by HTML and PDF, independently of browser scripts."""
import re

BACKGROUND_ROLES = {
    "conclusion": ("F0F5FD", 11, 9), "note-problem": ("FFF4F1", 9, 7),
    "note-improve": ("F0FAF6", 9, 7), "note-rewrite": ("F1F5FF", 9, 7),
    "note-pending": ("FFF9ED", 9, 7), "note-evidence": ("F5F7FA", 9, 7),
}


EXPORT_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.65; color: #25364d; }
h1 { font-size: 21pt; color: #16263c; margin: 0 0 18pt; }
h2 { font-size: 14.5pt; color: #fff; background-color: #17355d; padding: 9pt 11pt; margin: 22pt 0 12pt; page-break-after: avoid; }
h3 { font-size: 12pt; color: #165c76; background-color: #f1f6fa; padding: 7pt 9pt; margin: 17pt 0 9pt; page-break-after: avoid; }
h4 { font-size: 10.5pt; color: #17355d; margin: 14pt 0 7pt 8pt; page-break-after: avoid; }
p { margin: 6pt 0 9pt; page-break-inside: avoid; } ul,ol { padding-left: 20pt; margin: 6pt 0 10pt; }
li { margin-bottom: 6pt; }
p.conclusion { color: #1c548d; background-color: #f0f5fd; padding: 9pt 11pt; }
p.note-problem { color: #b64732; background-color: #fff4f1; padding: 7pt 9pt; }
p.note-improve { color: #087e65; background-color: #f0faf6; padding: 7pt 9pt; }
p.note-rewrite { color: #4265ad; background-color: #f1f5ff; padding: 7pt 9pt; }
p.note-pending { color: #9b6f26; background-color: #fff9ed; padding: 7pt 9pt; }
p.note-evidence { color: #6e7c8e; background-color: #f5f7fa; padding: 7pt 9pt; font-size: 9pt; }
p.note-action { color: #1b5b8b; padding-left: 9pt; }
p.source-meta { color: #667b90; font-size: 9pt; }
blockquote { color: #6e7c8e; margin: 8pt 0 8pt 12pt; }
table { border-collapse: collapse; width: 100%; margin: 10pt 0; }
th,td { border: 0.6pt solid #d9e2ef; padding: 6pt; vertical-align: top; }
th { background-color: #edf3f8; font-weight: bold; }
pre { white-space: pre-wrap; background-color: #f1f5f9; padding: 8pt; font-size: 9pt; }
img { max-width: 100%; } a { color: #2d70b0; }
"""


def decorate_export_html(body):
    if not str(body or "").strip():
        return ""
    from lxml import html
    root = html.fragment_fromstring(body, create_parent="div")
    conclusion, index, note_index = False, 0, 0
    rules = [
        (r"^问题[：:]", "problem"),
        (r"^(?:改进方式|突出建议|这项优势还没有表达充分)[：:]", "improve"),
        (r"^(?:基于已有事实的改写|改写示例)[：:]", "rewrite"),
        (r"^(?:还需补充|待确认|后续仍需确认|仍需核实的材料|进入条件|复核与调整)[：:]", "pending"),
        (r"^(?:原文依据|原文)[：:]", "evidence"),
        (r"^(?:交付物|完成标准|验收要点|对应要求|岗位要求|对照判断)[：:]", "action"),
    ]
    for element in root.iter():
        text = element.text_content().strip()
        if element.tag in {"h2", "h3", "h4"}:
            index += 1
            element.set("id", f"report-heading-{index}")
        if element.tag == "h2":
            conclusion = "核心结论" in text
        if element.tag == "p":
            role = "conclusion" if conclusion else "source-meta" if re.match(r"^(?:来源|地点)[：:]", text) else ""
            for pattern, name in rules:
                if re.match(pattern, text):
                    role = "note-" + name
                    break
            if role:
                element.set("class", role)
                note_index += 1
                element.set("id", f"report-note-{note_index}")
    return "".join(html.tostring(child, encoding="unicode", method="html") for child in root)
