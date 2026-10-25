"""原文引文定位与复制；不调用模型、服务或 Agent 工具。"""

import re


def copy_source_quote(quote: str, original: str) -> str | None:
    positions = [index for index, character in enumerate(original) if not character.isspace()]
    content = "".join(original[index] for index in positions)
    # 模型偶尔把列表编号「5、」写成「5. 」。只允许去掉开头的列表标记，再严格匹配正文。
    unnumbered = re.sub(r"^\s*(?:\d+[.．]\s+|\d+[、）)]\s*)", "", quote, count=1)
    for candidate in (quote, unnumbered):
        needle = "".join(character for character in candidate if not character.isspace())
        offset = content.find(needle) if needle else -1
        if offset >= 0:
            return original[positions[offset]:positions[offset + len(needle) - 1] + 1]
    return None
