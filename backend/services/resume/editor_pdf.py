"""Recover editable resume fields from the geometry of a text-layer PDF."""
import base64
from dataclasses import dataclass
from io import BytesIO
import re

import pymupdf as fitz
from PIL import Image

from .editor_document import EMAIL, PHONE, canonical_heading


@dataclass
class Line:
    text: str
    rect: fitz.Rect
    baseline: float
    size: float
    bold: bool
    formatted: str


def _join(left, right):
    if not left or not right:
        return left + right
    space = " " if re.search(r"[A-Za-z0-9]$", left) and re.match(r"[A-Za-z0-9]", right) else ""
    return left + space + right


def _rows(page):
    lines = []
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=flags)["blocks"]:
        for line in block.get("lines", []):
            spans = [span for span in line["spans"] if span["text"].strip() and "FontAwesome" not in span["font"]]
            if not spans:
                continue
            plain = "".join(span["text"] for span in spans).strip()
            bold_prefix = ""
            rest = plain.lstrip("• ").strip()
            if plain.startswith("•"):
                prefix = re.match(r"^([^：:]{1,30}[：:])", rest)
                if prefix and any(span["flags"] & 16 for span in spans):
                    bold_prefix = f"**{prefix[0]}**" + rest[len(prefix[0]):]
            lines.append(Line(plain, fitz.Rect(line["bbox"]), min(s["origin"][1] for s in spans),
                              max(s["size"] for s in spans), all(s["flags"] & 16 for s in spans),
                              "- " + (bold_prefix or rest) if plain.startswith("•") else plain))
    rows = []
    for line in sorted(lines, key=lambda line: line.baseline):
        if rows and abs(rows[-1][0].baseline - line.baseline) < 3.2:
            rows[-1].append(line)
        else:
            rows.append([line])
    return [sorted(row, key=lambda line: line.rect.x0) for row in rows]


def _web_links(page):
    return [(fitz.Rect(link["from"]), link["uri"]) for link in page.get_links()
            if link.get("uri", "").startswith(("https://", "http://")) and not re.search(r"[\s()|]", link["uri"])]


def _target_rows(items, label):
    return [item for item in items if 0 < item.baseline - label.baseline < 40
            and abs(item.rect.x0 - label.rect.x0) < 12 and not PHONE.search(item.text)]


def read_page_target(page):
    items = [line for row in _rows(page) for line in row]
    for line in items:
        if line.text.rstrip("：:") in {"求职意向", "目标岗位"}:
            if following := _target_rows(items, line):
                return following[0].text
    return ""


def _read_header(page, rows, cutoff):
    items = [line for row in rows for line in row]
    contact, extras, used = {}, [], set()
    candidates = [line for line in items if 18 <= line.size and 1 < len(line.text) <= 32
                  and abs((line.rect.x0 + line.rect.x1) / 2 - page.rect.width / 2) < page.rect.width * .18]
    if candidates:
        name = max(candidates, key=lambda line: line.size)
        contact["name"] = name.text
        used.add(id(name))
    for line in items:
        if line.text.rstrip("：:") in {"求职意向", "目标岗位"}:
            used.add(id(line))
            following = _target_rows(items, line)
            if following:
                contact["target"] = following[0].text
                used.add(id(following[0]))
            if len(following) > 1:
                extras.append({"label": "实习安排", "value": following[1].text})
                used.add(id(following[1]))
        if match := PHONE.search(line.text):
            contact.setdefault("phone", line.text[match.start():].strip())
            used.add(id(line))
        if match := EMAIL.search(line.text):
            contact.setdefault("email", match[0])
            used.add(id(line))
    for box, uri in _web_links(page):
        if box.y1 < cutoff:
            label = "GitHub" if "github.com/" in uri else "个人主页"
            extras.append({"label": label, "value": uri})
            used.update(id(line) for line in items if line.rect.intersects(box))
    if not any(item["label"] == "GitHub" for item in extras):
        for line in items:
            if match := re.search(r"github\.com/[\w.-]+", line.text, re.I):
                extras.append({"label": "GitHub", "value": "https://" + match[0]})
                used.add(id(line))
                break
    header = {"contact": contact, "extras": extras[:8]}
    # Only import an actual portrait-shaped image located in the header's right column.
    for item in page.get_image_info():
        rect = fitz.Rect(item["bbox"])
        if (rect.x0 > page.rect.width * .78 and rect.y1 < cutoff and 20 < rect.width < page.rect.width * .22
                and .65 * rect.width < rect.height < 2.1 * rect.width):
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=rect, alpha=False)
            image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            image.thumbnail((144, 200))
            stream = BytesIO()
            image.save(stream, "JPEG", quality=82)
            header["photo"] = base64.b64encode(stream.getvalue()).decode("ascii")
            break
    return header, [" ".join(line.text for line in row if id(line) not in used) for row in rows]


def read_layout(pdf):
    text = []
    header = {}
    heading = ""
    first = True
    bullet_x = None
    for page in pdf:
        rows = _rows(page)
        if not rows:
            return None  # Let the OCR path read mixed searchable/scanned files.
        links = _web_links(page)
        if first:
            index = next((i for i, row in enumerate(rows)
                          if len(row) == 1 and canonical_heading(row[0].text)), None)
            if index is None:
                return None
            if index:
                header, remaining = _read_header(page, rows[:index], rows[index][0].rect.y0)
                text.extend(line for line in remaining if line.strip())
            rows = rows[index:]
            if len(pdf) == 1 and rows[-1][0].baseline >= page.rect.height * .85:
                header["layout"] = "compact"
            first = False
        for row in rows:
            left = row[0]
            normalized = canonical_heading(left.text) if len(row) == 1 else None
            if normalized:
                heading = normalized
                text.append("## " + heading)
                bullet_x = None
                continue
            if heading in {"教育经历", "项目经历"} and len(row) == 3 and re.search(r"\b(?:19|20)\d{2}\b|至今", row[-1].text):
                name = left.text
                if heading == "项目经历":
                    for rect, uri in links:
                        if rect.intersects(left.rect):
                            name += f" [项目链接]({uri})"
                            break
                    if text and not text[-1].startswith("## "):
                        text.append("")
                text.append(" | ".join((name, row[1].text, row[2].text)))
                bullet_x = None
                continue
            if heading == "获奖情况" and all(line.text.startswith("•") or line.rect.x0 < page.rect.width * .45 for line in row):
                awards = [line.text.lstrip("• ").strip() for line in row if line.text.strip("• ")]
                if awards and any(line.text.startswith("•") for line in row):
                    text.append(" | ".join("- " + item for item in awards))
                    continue
            chunks = [line.formatted for line in row]
            value = " ".join(chunks)
            if left.text == "•" and len(row) > 1:
                value = "- " + " ".join(line.text.lstrip("• ") for line in row[1:])
            if value.startswith("- "):
                text.append(value)
                bullet_x = left.rect.x0
            elif bullet_x is not None and left.rect.x0 >= bullet_x + 3:
                text[-1] = _join(text[-1], value)
            else:
                text.append(value)
                bullet_x = None
    if not any(line.strip() and not line.startswith("## ") for line in text):
        return None
    return "\n".join(text), header
