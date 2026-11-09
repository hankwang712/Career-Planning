"""Whitespace-only reading layout shared by saved-report export paths."""
import re


def short_report_heading(text, limit=38):
    text = re.sub(r"\s+", " ", str(text).strip())
    pairs = {"（": "）", "(": ")", "“": "”", "「": "」", "《": "》"}
    stack, safe = [], 0
    for index, char in enumerate(text):
        if char in pairs:
            stack.append(pairs[char])
        elif stack and char == stack[-1]:
            stack.pop()
        if not stack:
            if char in "：:，,。；;":
                return text[:index] if index <= limit else text[:safe] + "…"
            if index < limit:
                safe = index + 1
        if index >= limit:
            return text[:safe or limit] + "…"
    return text


def structure_report_markdown(text: str) -> str:
    """Upgrade legacy priority paragraphs in reading/export views, preserving the saved source."""
    pending = []
    has_independent_work = "独立开发" in str(text or "")
    pattern = r"(^###\s+(?:\d{1,2}(?:\.\d{1,2})*[.、]?\s+)?优先修改(?:顺序)?\s*\n)([\s\S]*?)(?=^#{1,3}\s|\Z)"
    def priorities(match):
        body = match[2]
        if re.search(r"^####\s", body, re.M):
            return match[0]
        blocks = []
        for paragraph in re.split(r"\n\s*\n", body.strip()):
            if not paragraph.strip():
                continue
            if paragraph.strip().startswith("仍需核实的材料："):
                pending.append(paragraph.strip())
            elif re.match(r"\s*(?:\d+\.\s|[-*+]\s|>)", paragraph):
                blocks.append(paragraph)
            else:
                pieces = re.split(r"[，；。]\s*完成标准[为是：:]", paragraph.strip(), maxsplit=1)
                action = pieces[0]
                if has_independent_work:
                    action = re.sub(r"(?:所有|全部|[两二三四五六七八九十]+段)经历的个人分工", "团队经历的个人分工", action)
                heading = short_report_heading(action)
                blocks.append("#### " + heading)
                detail = action[len(heading):].lstrip("：:，,。；; ") if action.startswith(heading) else action
                if detail and not re.match(r"^(?:便于|以便|从而)", detail):
                    blocks.append(detail)
                if len(pieces) > 1:
                    blocks.append("**验收要点：**" + pieces[1].lstrip("：: "))
        return match[1] + "\n" + "\n\n".join(blocks) + "\n\n"
    pieces = re.split(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)", str(text or ""))
    text = "".join(piece if piece.startswith(("```", "~~~")) else re.sub(pattern, priorities, piece, flags=re.M) for piece in pieces)
    if pending:
        text = text.rstrip() + "\n\n### 待补材料备查\n\n" + "\n\n".join(pending)
    return text


def number_report_headings(text: str) -> str:
    """Literal, idempotent numbering shared by report generation and every export."""
    counts = [0, 0, 0]
    fence = None
    output = []
    for line in str(text or "").splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker[1][0]
            fence = None if fence == token else token if fence is None else fence
        heading = None if fence else re.match(r"^(#{2,4})\s+(.+)$", line)
        if heading:
            level = len(heading[1]) - 2
            counts[level] += 1
            for deeper in range(level + 1, 3):
                counts[deeper] = 0
            # Do not mistake a graduation year such as 2027 for a heading number.
            title = re.sub(r"^\d{1,2}(?:\.\d{1,2})*[.、．]?\s+", "", heading[2])
            number = ".".join(str(value or 1) for value in counts[:level + 1])
            line = f"{heading[1]} {number} {title}"
        output.append(line)
    return "\n".join(output)


def readable_markdown(text: str) -> str:
    def paragraph(block):
        if len(block) < 260 or re.search(r"^(?: {4}|\t)|(?:^|\n)\s*(?:#{1,6}\s|>|[-*+]\s|\d+[.)]\s|\|)", block):
            return block
        # Links, code and quotations are indivisible; splitting them changes Markdown meaning.
        ranges = {m.start(): m.end() for m in re.finditer(r"`[^`\n]*`|!?\[[^\]\n]*\]\([^\n)]*\)|https?://[^\s<>]+", block)}
        pairs = dict(zip("「『“‘《（(【[", "」』”’》）)】]"))
        stack, parts, start, index = [], [], 0, 0
        while index < len(block):
            if index in ranges:
                index = ranges[index]
                continue
            char = block[index]
            if char == "\\":
                index += 2
                continue
            if char in pairs:
                stack.append(pairs[char])
            elif stack and char == stack[-1]:
                stack.pop()
            boundary = char in "。！？；" or re.search(r"[。！？；][”’」』》）】)]*$", block[max(start, index - 12):index + 1])
            if not stack and boundary and index - start >= 150 and len(block) - index > 60:
                parts.append(block[start:index + 1].strip())
                start = index + 1
            index += 1
        parts.append(block[start:].strip())
        return "\n\n".join(parts)
    pieces = re.split(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)", str(text or "").replace("\r\n", "\n"))
    return "".join(piece if piece.startswith(("```", "~~~")) else "\n\n".join(paragraph(block) for block in re.split(r"\n[ \t]*\n", piece)) for piece in pieces)
