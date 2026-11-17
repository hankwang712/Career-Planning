"""简历文本提取、OCR、结构化与岗位匹配分析。"""

import json
import logging
import os
import re
import shutil
import time
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename

from services import llm_env
from services.appctx import get_app
from services.llm_calls import call_markdown_chat, call_structured_chat
from services.resume import (
    build_fallback_resume_highlight_deck,
    build_job_payload_from_text,
    build_matcher_state,
    build_resume_text_payload,
    HR_JUDGE_PROMPT,
    RESUME_REVIEW_PROMPT,
    STRUCTURED_RESUME_PROMPT,
    STRUCTURED_RESUME_SCHEMA,
)
from services.resume.diagnosis_ui import (
    build_diagnosis_ui_extract_prompt,
    DIAGNOSIS_UI_EXTRACT_SYSTEM,
    diagnosis_ui_non_empty,
    normalize_diagnosis_ui,
)
from services.user_state import _user_upload_dir


try:
    from PIL import Image, ImageFilter, ImageOps
except Exception:  # pragma: no cover - optional dependency
    Image = None
    ImageFilter = None
    ImageOps = None

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None

try:
    import pymupdf as fitz  # PyMuPDF
except Exception:  # pragma: no cover - optional dependency
    fitz = None

logger = logging.getLogger(__name__)
try:
    import pdfplumber
except Exception:  # pragma: no cover - optional dependency
    pdfplumber = None

try:
    import pytesseract
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None




RESUME_MAX_FILE_SIZE = 12 * 1024 * 1024


RESUME_MAX_PAGES = 20


RESUME_OCR_TIMEOUT_SECONDS = 35


RESUME_MAX_TEXT_CHARS = 24000


def _allowed_pdf(file_storage):
    filename = str(getattr(file_storage, "filename", "") or "")
    if not filename.lower().endswith(".pdf"):
        return False
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False
    current = stream.tell()
    head = stream.read(5)
    stream.seek(current)
    return bool(head.startswith(b"%PDF"))


def _allowed_resume_upload(file_storage):
    filename = str(getattr(file_storage, "filename", "") or "")
    suffix = os.path.splitext(filename)[1].lower()
    if suffix not in {".pdf", ".docx"}:
        return False
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False
    current = stream.tell()
    head = stream.read(8)
    stream.seek(current)
    if suffix == ".pdf":
        return bool(head.startswith(b"%PDF"))
    return bool(head.startswith(b"PK"))


def _save_resume_upload(file_storage, username):
    if not _allowed_resume_upload(file_storage):
        raise ValueError("仅支持 PDF 或 DOCX 简历文件上传。")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError("上传文件为空。")
    if size > RESUME_MAX_FILE_SIZE:
        raise ValueError(f"简历文件过大，请控制在 {RESUME_MAX_FILE_SIZE // (1024 * 1024)}MB 内。")

    target_dir = _user_upload_dir(username)
    os.makedirs(target_dir, exist_ok=True)
    original_name = file_storage.filename or "resume.pdf"
    safe = secure_filename(original_name) or "resume.pdf"
    suffix = os.path.splitext(safe)[1].lower() or os.path.splitext(original_name)[1].lower()
    if suffix not in {".pdf", ".docx"}:
        raise ValueError("仅支持 PDF 或 DOCX 简历文件上传。")
    if not safe.lower().endswith(suffix):
        safe += suffix
    saved_name = f"{int(time.time())}_{uuid.uuid4().hex[:8]}_{safe}"
    target_path = os.path.join(target_dir, saved_name)
    file_storage.save(target_path)
    return target_path, saved_name, size, suffix.lstrip(".")


def _save_resume_pdf(file_storage, username):
    if not _allowed_pdf(file_storage):
        raise ValueError("仅支持 PDF 文件上传。")

    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size <= 0:
        raise ValueError("上传文件为空。")
    if size > RESUME_MAX_FILE_SIZE:
        raise ValueError(f"PDF 文件过大，请控制在 {RESUME_MAX_FILE_SIZE // (1024 * 1024)}MB 内。")

    target_dir = _user_upload_dir(username)
    os.makedirs(target_dir, exist_ok=True)
    safe = secure_filename(file_storage.filename or "resume.pdf") or "resume.pdf"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    saved_name = f"{int(time.time())}_{safe}"
    target_path = os.path.join(target_dir, saved_name)
    file_storage.save(target_path)
    return target_path, saved_name, size


def _normalize_resume_text(raw_text):
    return re.sub(r"\s+", " ", str(raw_text or "")).strip()


def _resume_text_quality_score(raw_text):
    text = _normalize_resume_text(raw_text)
    if not text:
        return 0.0
    compact = re.sub(r"\s+", "", text)
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", compact))
    latin_count = len(re.findall(r"[A-Za-z]", compact))
    digit_count = len(re.findall(r"\d", compact))
    symbol_bonus = len(re.findall(r"[@:/.()%+\-]", compact))
    noise_penalty = len(re.findall(r"[=~`|_^<>*]", compact))
    return (
        len(compact) * 0.6
        + cjk_count * 1.8
        + latin_count * 0.25
        + digit_count * 0.2
        + symbol_bonus * 0.1
        - noise_penalty * 0.8
    )


def _resume_text_meaningful_ratio(raw_text):
    text = _normalize_resume_text(raw_text)
    if not text:
        return 0.0
    compact = re.sub(r"\s+", "", text)
    meaningful = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9@:/.()%+\-]", compact))
    return meaningful / max(len(compact), 1)


def _merge_resume_page_candidates(*candidate_groups):
    merged = {}
    for group in candidate_groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            page_no = int(item.get("page_no") or 0)
            if page_no <= 0:
                continue
            text = _normalize_resume_text(item.get("text") or item.get("content") or item.get("markdown") or "")
            if not text:
                continue
            score = _resume_text_quality_score(text)
            previous = merged.get(page_no)
            if previous is None or score > previous["score"]:
                merged[page_no] = {
                    "page_no": page_no,
                    "source": str(item.get("source") or "text"),
                    "text": text,
                    "score": score,
                }
    result = []
    for page_no in sorted(merged.keys())[:RESUME_MAX_PAGES]:
        payload = dict(merged[page_no])
        payload.pop("score", None)
        result.append(payload)
    return result


def _resolve_tesseract_executable():
    if pytesseract is None:
        return ""
    current = str(getattr(pytesseract.pytesseract, "tesseract_cmd", "") or "").strip()
    candidates = [
        current,
        os.environ.get("TESSERACT_CMD", ""),
        "tesseract",
        r"D:\software\OCR\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate:
            continue
        if os.path.isabs(candidate) and os.path.exists(candidate):
            return candidate
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return ""


def _configure_tesseract_command():
    executable = _resolve_tesseract_executable()
    if executable and pytesseract is not None:
        pytesseract.pytesseract.tesseract_cmd = executable
    return executable


def _available_tesseract_languages():
    if pytesseract is None:
        return []
    _configure_tesseract_command()
    try:
        return [str(item or "").strip() for item in pytesseract.get_languages(config="") if str(item or "").strip()]
    except Exception as exc:
        logger.warning("无法读取 Tesseract 语言列表：%s", type(exc).__name__)
        return []


def _resolve_resume_ocr_lang():
    langs = {item.lower() for item in _available_tesseract_languages()}
    if {"chi_sim", "eng"}.issubset(langs):
        return "chi_sim+eng"
    if "chi_sim" in langs:
        return "chi_sim"
    if "eng" in langs:
        return "eng"
    return ""


def _prepare_resume_ocr_image(image):
    if image is None or Image is None:
        return image
    prepared = image.convert("L")
    if ImageOps is not None:
        prepared = ImageOps.autocontrast(prepared)
    if ImageFilter is not None:
        prepared = prepared.filter(ImageFilter.MedianFilter(size=3))
    return prepared


def _run_resume_ocr(image, lang):
    if pytesseract is None or image is None or not lang:
        return ""
    _configure_tesseract_command()
    primary_text = ""
    try:
        primary_text = pytesseract.image_to_string(image, lang=lang, config="--oem 3 --psm 6")
    except Exception as exc:
        logger.warning("OCR 首次识别失败：%s", type(exc).__name__)
        primary_text = ""
    primary_score = _resume_text_quality_score(primary_text)
    if primary_score >= 900:
        return _normalize_resume_text(primary_text)

    prepared_image = _prepare_resume_ocr_image(image)
    if prepared_image is image:
        return _normalize_resume_text(primary_text)

    try:
        fallback_text = pytesseract.image_to_string(prepared_image, lang=lang, config="--oem 3 --psm 6")
    except Exception as exc:
        logger.warning("OCR 预处理后识别失败：%s", type(exc).__name__)
        fallback_text = ""

    if _resume_text_quality_score(fallback_text) > primary_score:
        return _normalize_resume_text(fallback_text)
    return _normalize_resume_text(primary_text)


def _extract_pdf_text_pages(pdf_path):
    pypdf_pages = []
    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            for idx, page in enumerate(reader.pages[:RESUME_MAX_PAGES], start=1):
                text = _normalize_resume_text(page.extract_text() or "")
                if text:
                    pypdf_pages.append({"page_no": idx, "source": "pypdf", "text": text})
        except Exception as exc:
            logger.warning("pypdf 读取简历失败，改用其他引擎：%s", type(exc).__name__)

    plumber_pages = []
    if pdfplumber is not None:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for idx, page in enumerate(pdf.pages[:RESUME_MAX_PAGES], start=1):
                    variants = []
                    for kwargs in ({}, {"layout": True}):
                        try:
                            variants.append(page.extract_text(**kwargs) or "")
                        except TypeError:
                            variants.append(page.extract_text() or "")
                        except Exception as exc:
                            logger.debug("pdfplumber 页面解析失败：%s", type(exc).__name__)
                            continue
                    text = max(variants, key=_resume_text_quality_score, default="")
                    text = _normalize_resume_text(text)
                    if text:
                        plumber_pages.append({"page_no": idx, "source": "pdfplumber", "text": text})
        except Exception as exc:
            logger.warning("pdfplumber 读取简历失败，改用其他引擎：%s", type(exc).__name__)

    pymupdf_pages = []
    if fitz is not None:
        try:
            with fitz.open(pdf_path) as doc:
                for idx in range(min(len(doc), RESUME_MAX_PAGES)):
                    text = _normalize_resume_text(doc[idx].get_text("text") or "")
                    if text:
                        pymupdf_pages.append({"page_no": idx + 1, "source": "pymupdf", "text": text})
        except Exception as exc:
            logger.warning("PyMuPDF 读取简历失败：%s", type(exc).__name__)

    return _merge_resume_page_candidates(pypdf_pages, plumber_pages, pymupdf_pages)


def _should_fallback_ocr(text_pages, *_):
    if not text_pages:
        return True
    total_chars = 0
    meaningful_chars = 0
    for item in text_pages:
        if isinstance(item, dict):
            text = item.get("text") or item.get("content") or item.get("markdown") or ""
        else:
            text = item
        normalized = _normalize_resume_text(text)
        compact = re.sub(r"\s+", "", normalized)
        total_chars += len(compact)
        meaningful_chars += len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9@:/.()%+\-]", compact))
    meaningful_ratio = meaningful_chars / max(total_chars, 1)
    return total_chars < 240 or meaningful_ratio < 0.42


def _ocr_pdf_pages(pdf_path):
    if fitz is None or pytesseract is None or Image is None:
        return []
    ocr_lang = _resolve_resume_ocr_lang()
    if not ocr_lang:
        return []

    start_at = time.monotonic()
    pages = []
    try:
        with fitz.open(pdf_path) as doc:
            for idx in range(min(len(doc), RESUME_MAX_PAGES)):
                if time.monotonic() - start_at > RESUME_OCR_TIMEOUT_SECONDS:
                    break
                pix = doc[idx].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                text = _run_resume_ocr(image, ocr_lang)
                if text:
                    pages.append({"page_no": idx + 1, "source": f"ocr:{ocr_lang}", "text": text})
    except Exception as exc:
        logger.warning("扫描件 OCR 中断，返回已识别的 %d 页：%s", len(pages), type(exc).__name__)
        return pages
    return pages


def _resume_text_bundle(text_pages):
    chunks = []
    for item in text_pages[:RESUME_MAX_PAGES]:
        content = str(item.get("text") or "").strip()
        if not content:
            continue
        chunks.append(f"[第{item.get('page_no')}页/{item.get('source')}]\n{content}")
    joined = "\n\n".join(chunks)
    return joined[:RESUME_MAX_TEXT_CHARS]


def _infer_resume_basics_from_text(text):
    compact = re.sub(r"\s+", " ", str(text or ""))
    basics = {
        "major": "",
        "education_level": "",
        "target_city": "",
        "target_direction": "",
    }
    if re.search(r"博士|phd", compact, re.IGNORECASE):
        basics["education_level"] = "博士"
    elif re.search(r"硕士|研究生|master", compact, re.IGNORECASE):
        basics["education_level"] = "硕士"
    elif re.search(r"本科|学士|bachelor", compact, re.IGNORECASE):
        basics["education_level"] = "本科"
    elif re.search(r"大专|专科|college diploma", compact, re.IGNORECASE):
        basics["education_level"] = "大专"

    major_match = re.search(r"(?:专业|主修)\s*[:：]?\s*([^\n，。；;]{2,30})", compact, re.IGNORECASE)
    if major_match:
        basics["major"] = str(major_match.group(1) or "").strip()

    city_match = re.search(r"(?:意向城市|求职意向|期望城市)\s*[:：]?\s*([^\n。；;]{2,40})", compact, re.IGNORECASE)
    if city_match:
        basics["target_city"] = str(city_match.group(1) or "").strip()

    direction_match = re.search(r"(?:目标方向|意向岗位|求职方向|目标岗位)\s*[:：]?\s*([^\n。；;]{2,40})", compact, re.IGNORECASE)
    if direction_match:
        basics["target_direction"] = str(direction_match.group(1) or "").strip()
    return basics


def _build_resume_extract_prompt():
    return "\n".join(
        [
            "你是中文简历结构化助手。请严格基于输入简历输出 JSON，不要输出任何额外说明。",
            "输出结构需包含 candidate_summary、basics（至少包含 major、education_level、target_city、target_direction、gender）、roles_detected、leadership_signals、project_highlights、skills、capability_scores、evidence_spans、confidence。",
            "- 严禁编造。",
            "- 缺失字段使用 unknown、空字符串或空数组。",
            "- 所有分数范围为 0-100，confidence 范围为 0-1。",
            "- 输出必须是 JSON 对象本身。",
        ]
    )


def _normalize_resume_profile(raw_payload):
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    basics = payload.get("basics") if isinstance(payload.get("basics"), dict) else {}
    capability_scores = payload.get("capability_scores") if isinstance(payload.get("capability_scores"), dict) else {}
    return {
        "candidate_summary": str(payload.get("candidate_summary") or "unknown").strip() or "unknown",
        "basics": {
            "gender": str(basics.get("gender") or basics.get("sex") or "").strip(),
            "major": str(basics.get("major") or "").strip(),
            "education_level": str(basics.get("education_level") or basics.get("grade") or "").strip(),
            "target_city": str(basics.get("target_city") or basics.get("targetCity") or "").strip(),
            "target_direction": str(basics.get("target_direction") or basics.get("targetDirection") or "").strip(),
        },
        "roles_detected": payload.get("roles_detected") if isinstance(payload.get("roles_detected"), list) else [],
        "leadership_signals": payload.get("leadership_signals") if isinstance(payload.get("leadership_signals"), list) else [],
        "competition_records": payload.get("competition_records") if isinstance(payload.get("competition_records"), list) else [],
        "project_highlights": payload.get("project_highlights") if isinstance(payload.get("project_highlights"), list) else [],
        "skills": payload.get("skills") if isinstance(payload.get("skills"), list) else [],
        "evidence_spans": payload.get("evidence_spans") if isinstance(payload.get("evidence_spans"), list) else [],
        "capability_scores": {
            "communication": int(float(capability_scores.get("communication") or 0)),
            "execution": int(float(capability_scores.get("execution") or 0)),
            "stress_resilience": int(float(capability_scores.get("stress_resilience") or 0)),
            "innovation": int(float(capability_scores.get("innovation") or 0)),
            "collaboration": int(float(capability_scores.get("collaboration") or 0)),
            "leadership": int(float(capability_scores.get("leadership") or 0)),
        },
        "confidence": max(0.0, min(1.0, float(payload.get("confidence") or 0))),
    }


def _extract_resume_profile(pdf_path, progress_callback=None, runtime_llm=None):
    raise RuntimeError("Legacy resume profile extractor is disabled. Use matcher pipeline instead.")


RESUME_HIGHLIGHT_DECK_SYSTEM = """
你是**资深职业规划顾问 + 技术招聘负责人视角**的合体：对用户温暖清晰，对岗位门槛判断冷静。
任务：只阅读下方「系统信号」与「简历分析报告节选」，输出**一层**可被用户 10 秒内读完的 JSON，用于产品首屏；**禁止**输出 Markdown、代码块、注释或任何 JSON 外文字。

# 输出目标（必须满足）
- 用户应能直接回答：**我最强在哪、最大风险在哪、下一步改哪三处**；有 JD 时还应回答**现在投是否划算**。
- **信息密度高**：每句话都要有判断或证据，不写正确的废话（如「建议优化简历」而不说改什么）。
- **禁止**：堆砌字段名（如「structured_resume」「关键词」）；复述系统 JSON；空泛形容词（「较强」「不错」「丰富」若无证据支撑须改写为可核对表述）。
- **称呼**：`candidate_summary` 里若出现看似邮箱昵称的英文片段（如短串、全小写），**不要**照抄为句首称呼；可改为「你的简历…」或直接以判断起句，避免「Sime，已提取…」这类观感。

# 各字段细则

## core_conclusion（约 140～420 字，中文）
- **结构**：第 1～2 句给**总判断**；随后用「因为…」串起 **1～2 条**最关键依据（经历/项目/成果/匹配度），**不要**平均铺开报告里所有小节。
- **resume_review（无 JD）**：写清三件事的压缩版——**更像哪类候选人**、**主线是否集中**、**当前最大成长瓶颈**；可自然提到 1～2 个建议探索方向，但不要写成岗位承诺。
- **job_match（有 JD）**：**首句必须是投递态度**（用自然中文，例如「与目标岗位相比，当前简历属于…」），第二句起再写与**岗位核心门槛**（硬技能/年限/场景/成果类型）的关系；若报告认为有关键硬伤，必须在结论里点出**一个**最致命的，而不是罗列。

## identity_tag（≤20 字，可空字符串）
- 一句**画像标签**，像给人起外号但要专业：例如「工程实践驱动型」「项目强但叙事散」「转岗中·需对齐 JD 话术」。勿与 core_conclusion 完全重复。

## highlight_evidence（**最多 2 条**）
- 每条：`headline` = **可识别的经历锚点**（公司/项目名/角色，≤24 字）；`why` = **为何这条能支撑你的判断**（尽量含**可核对要素**：技术栈/职责/结果形态，避免纯形容词）。
- 若材料不足，宁可 **1 条写深**，也不要 2 条空洞。

## key_risks（**最多 3 条**）
- 按**杀伤力**排序：优先写会导致 **简历筛不过 / 面试一追就穿 / 与 JD 核心场景不符** 的问题。
- 每条一句，开头可用「风险：」或直接陈述；**不要**把「错别字」「格式」与「无岗位相关成果」并列——永远先写后者。

## next_actions（**最多 3 条**）
- **必须**以动词开头（「把…」「删掉…」「在…下补一行…」）。
- 每条指向**简历上可改的一处具体位置或一类表述**，避免「提升表达能力」「多学习」等不可执行句。
- 有 JD 时，至少 **1 条**应显式对齐 **missing_keywords 或岗位硬性要求**（用自然语言，不要机械堆词）。

## substitution_opportunities（**0～2 条**，数组）
- 仅当你判断：**能力/经历可能存在，但简历用语与岗位话术未对齐** 时填写；写清「可以把哪类经历改写成岗位听得懂的一句话」。
- 若不存在或不确定，输出 **[]**。

## apply_verdict 与 apply_verdict_label（仅 job_match 有意义）
- `not_applicable`：analysis_mode 为 resume_review 时**必须**使用；此时 `apply_verdict_label` 为 **空字符串**。
- `direct_ok`：核心门槛基本满足，缺的是**表达或锦上添花**，投递**可尝试**（仍可能有面试风险）。
- `revise_first`：**有明显缺口或证据不足**，但**改简历 1～2 轮**后值得投。
- `risky`：**硬门槛差太远**或**证据链断裂**，强投性价比低；用户应先换目标或补经历再投。
- `apply_verdict_label`：≤12 字中文，与 verdict 一致，例如「可尝试投递」「建议改后再投」「暂不建议硬投」。

# JSON Schema（键名与层级必须完全一致）
{
  "core_conclusion": "string",
  "identity_tag": "string",
  "highlight_evidence": [{"headline": "string", "why": "string"}],
  "key_risks": ["string"],
  "next_actions": ["string"],
  "substitution_opportunities": ["string"],
  "apply_verdict": "not_applicable|direct_ok|revise_first|risky",
  "apply_verdict_label": "string"
}
""".strip()


def _normalize_resume_highlight_deck(raw, profile, matcher, analysis_mode):
    fb = build_fallback_resume_highlight_deck(profile, matcher, analysis_mode)
    if not isinstance(raw, dict):
        return fb
    out = dict(fb)
    cc = str(raw.get("core_conclusion") or "").strip()
    if len(cc) >= 40:
        out["core_conclusion"] = cc[:900]
    it = str(raw.get("identity_tag") or "").strip()
    if it:
        out["identity_tag"] = it[:48]
    he = raw.get("highlight_evidence")
    cleaned_he = []
    if isinstance(he, list):
        for item in he[:2]:
            if not isinstance(item, dict):
                continue
            hl = str(item.get("headline") or item.get("title") or "").strip()
            why = str(item.get("why") or item.get("reason") or "").strip()
            if hl or why:
                cleaned_he.append({"headline": (hl or "亮点证据")[:120], "why": (why or hl)[:420]})
    if cleaned_he:
        out["highlight_evidence"] = cleaned_he
    kr = raw.get("key_risks")
    if isinstance(kr, list):
        kr2 = [str(x).strip() for x in kr if str(x).strip()][:3]
        if kr2:
            out["key_risks"] = kr2
    na = raw.get("next_actions")
    if isinstance(na, list):
        na2 = [str(x).strip() for x in na if str(x).strip()][:3]
        if na2:
            out["next_actions"] = na2
    so = raw.get("substitution_opportunities")
    if isinstance(so, list):
        so2 = [str(x).strip() for x in so if str(x).strip()][:2]
        if so2:
            out["substitution_opportunities"] = so2
    av = str(raw.get("apply_verdict") or "").strip()
    if av in {"not_applicable", "direct_ok", "revise_first", "risky"}:
        out["apply_verdict"] = av
    if analysis_mode == "resume_review":
        out["apply_verdict"] = "not_applicable"
        out["apply_verdict_label"] = ""
    lbl = str(raw.get("apply_verdict_label") or "").strip()
    if lbl and analysis_mode == "job_match":
        out["apply_verdict_label"] = lbl[:32]
    return out


def _extract_resume_highlight_deck_llm(base_url, api_key, model, matcher_state, analysis_mode):
    profile = matcher_state.get("profile") if isinstance(matcher_state.get("profile"), dict) else {}
    matcher = matcher_state.get("matcher") if isinstance(matcher_state.get("matcher"), dict) else {}
    resume_ov = matcher.get("resume_overview") if isinstance(matcher.get("resume_overview"), dict) else {}
    caps = profile.get("capability_scores") if isinstance(profile.get("capability_scores"), dict) else {}
    cap_pairs = []
    if caps:
        try:
            ranked = sorted(
                ((str(k), int(float(v))) for k, v in caps.items() if str(k) != "matching"),
                key=lambda x: -x[1],
            )[:3]
            cap_pairs = [{"dimension": k, "score": v} for k, v in ranked]
        except (TypeError, ValueError):
            cap_pairs = []

    structured_job = matcher_state.get("structured_job") if isinstance(matcher_state.get("structured_job"), dict) else {}
    job_qual = structured_job.get("qualifications") if isinstance(structured_job.get("qualifications"), dict) else {}
    company_profile = structured_job.get("company_profile") if isinstance(structured_job.get("company_profile"), dict) else {}

    signals = {
        "analysis_mode": analysis_mode,
        "candidate_summary": str(profile.get("candidate_summary") or "")[:900],
        "roles_detected": [
            str(r.get("role") or "").strip()
            for r in (profile.get("roles_detected") or [])
            if isinstance(r, dict) and str(r.get("role") or "").strip()
        ][:8],
        "uncertainty_items": [
            {"item": str(u.get("item") or "").strip(), "reason": str(u.get("reason") or "").strip()[:200]}
            for u in (profile.get("uncertainty_layer") or [])
            if isinstance(u, dict) and str(u.get("item") or "").strip()
        ][:6],
        "capability_top": cap_pairs,
        "resume_experience_count": resume_ov.get("experience_count"),
        "resume_project_count": resume_ov.get("project_count"),
        "resume_skill_count": resume_ov.get("skill_count"),
        "matched_keywords": (matcher.get("matched_keywords") or [])[:22],
        "missing_keywords": (matcher.get("missing_keywords") or [])[:22],
        "job_title": (matcher.get("job_overview") or {}).get("job_title") or "",
        "job_company": str(company_profile.get("company_name") or "").strip()[:80],
        "job_summary_snippet": str(structured_job.get("job_summary") or "").strip()[:420],
        "job_required_snippets": [str(x).strip() for x in (job_qual.get("required") or []) if str(x).strip()][:8],
        "job_preferred_snippets": [str(x).strip() for x in (job_qual.get("preferred") or []) if str(x).strip()][:6],
        "recommended_directions": (matcher.get("recommended_directions") or [])[:8],
    }
    excerpt = str(matcher_state.get("analysis_result") or "")[:16000]
    user_body = (
        "请仅输出一个合法 JSON 对象，键名必须与 system 中的 Schema 完全一致，不要输出 ``` 代码围栏。\n\n"
        "【系统已提取信号（JSON）】\n"
        + json.dumps(signals, ensure_ascii=False)
        + "\n\n【简历分析报告节选】\n"
        + excerpt
    )
    return call_structured_chat(
        base_url,
        api_key,
        model,
        [{"role": "user", "content": user_body}],
        system_prompt=RESUME_HIGHLIGHT_DECK_SYSTEM,
        max_tokens=2800,
    )


def _analyze_resume_matcher(storage_path, job_description, progress_callback=None, runtime_llm=None):
    def _report(stage, detail):
        if callable(progress_callback):
            try:
                progress_callback(stage, detail)
            except Exception as exc:
                logger.warning("简历分析进度回调失败：%s", type(exc).__name__)

    job_text = str(job_description or "").strip()
    analysis_mode = "job_match" if job_text else "resume_review"

    _report("extract_resume", "正在提取简历文本")
    text_payload = build_resume_text_payload(
        storage_path,
        extract_pdf_text_pages=_extract_pdf_text_pages,
        should_fallback_ocr=_should_fallback_ocr,
        ocr_pdf_pages=_ocr_pdf_pages,
        max_pages=RESUME_MAX_PAGES,
        max_chars=RESUME_MAX_TEXT_CHARS,
    )
    resume_text = str(text_payload.get("plain_text") or "").strip()
    if not resume_text:
        raise ValueError("未能从简历中提取到有效文本，请检查文件内容。")

    if isinstance(runtime_llm, (tuple, list)) and len(runtime_llm) >= 3:
        base_url = str(runtime_llm[0] or "").strip()
        api_key = str(runtime_llm[1] or "").strip()
        model = str(runtime_llm[2] or "").strip()
    else:
        base_url, api_key, model = llm_env.chat_runtime()
    if not base_url or not api_key:
        raise ValueError("模型尚未配置，请在服务器 .env 中补全 AI_CHAT_BASE_URL、AI_CHAT_API_KEY、AI_CHAT_MODEL 后重启。")
    if not model:
        model = "gpt-4o-mini"

    _report("structured_resume", "正在提取结构化简历")
    resume_schema_json = json.dumps(STRUCTURED_RESUME_SCHEMA, ensure_ascii=False, indent=2)
    structured_resume = call_structured_chat(
        base_url,
        api_key,
        model,
        [{"role": "user", "content": "请仅输出符合 schema 的 JSON。"}],
        system_prompt=STRUCTURED_RESUME_PROMPT.format(resume_schema_json, resume_text),
        max_tokens=2600,
    )

    structured_job = {}
    if analysis_mode == "job_match":
        _report("job_context", "正在理解岗位文本")
        structured_job = build_job_payload_from_text(job_text)
        _report("hr_judge", "正在生成岗位匹配分析（深度五步审计）")
        analysis_markdown = call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": "请输出最终 Markdown 分析报告。"}],
            system_prompt=HR_JUDGE_PROMPT.format(
                datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                Job_Description=job_text,
                raw_resume=resume_text,
            ),
            max_tokens=6000,
        )
    else:
        _report("resume_review", "正在生成简历诊断")
        analysis_markdown = call_markdown_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": "请输出最终 Markdown 分析报告。"}],
            system_prompt=RESUME_REVIEW_PROMPT.format(
                datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                raw_resume=resume_text,
            ),
            max_tokens=3200,
        )

    extracted_skills = None
    try:
        from services.skills.extraction import SkillExtractor
        _report("skill_alignment", "正在提取原文技能并对齐标准技能表")
        extracted_skills = SkillExtractor((base_url, api_key, model)).extract(resume_text, job_text)
    except Exception as exc:
        get_app().logger.warning("技能抽取失败，保留词表可核对结果：%s", type(exc).__name__)
    matcher_state = build_matcher_state(
        structured_resume=structured_resume,
        structured_job=structured_job,
        analysis_markdown=analysis_markdown,
        job_description=job_text,
        extracted_skills=extracted_skills,
    )
    _report("highlight_deck", "正在提炼核心结论与亮点")
    try:
        raw_deck = _extract_resume_highlight_deck_llm(base_url, api_key, model, matcher_state, analysis_mode)
        matcher_state["resume_highlight_deck"] = _normalize_resume_highlight_deck(
            raw_deck,
            matcher_state.get("profile"),
            matcher_state.get("matcher"),
            analysis_mode,
        )
    except Exception as exc:
        get_app().logger.warning("resume highlight deck extraction failed: %s", exc)
        matcher_state["resume_highlight_deck"] = build_fallback_resume_highlight_deck(
            matcher_state.get("profile"),
            matcher_state.get("matcher"),
            analysis_mode,
        )

    _report("diagnosis_ui", "正在提炼深度审计结构化版面")
    try:
        profile_for_ui = matcher_state.get("profile") if isinstance(matcher_state.get("profile"), dict) else {}
        basics_for_ui = profile_for_ui.get("basics") if isinstance(profile_for_ui.get("basics"), dict) else {}
        canonical_resume_name = str(basics_for_ui.get("name") or "").strip()
        cand_sum = str(profile_for_ui.get("candidate_summary") or "").strip()
        user_ui = build_diagnosis_ui_extract_prompt(
            matcher_state.get("analysis_result") or "",
            cand_sum,
            analysis_mode,
            candidate_legal_name=canonical_resume_name,
        )
        raw_diagnosis_ui = call_structured_chat(
            base_url,
            api_key,
            model,
            [{"role": "user", "content": user_ui}],
            system_prompt=DIAGNOSIS_UI_EXTRACT_SYSTEM,
            max_tokens=3800,
        )
        diagnosis_ui = normalize_diagnosis_ui(raw_diagnosis_ui, canonical_name=canonical_resume_name)
        if diagnosis_ui_non_empty(diagnosis_ui):
            matcher_state["matcher"]["diagnosis_ui"] = diagnosis_ui
    except Exception as exc:
        get_app().logger.warning("diagnosis_ui extract failed: %s", exc)

    analysis_meta = dict(text_payload.get("analysis_meta") or {})
    analysis_meta.update(
        {
            "parsed_at": int(time.time()),
            "job_description_length": len(job_text),
            "analysis_mode": analysis_mode,
            "model": model,
            "resume_keyword_count": len((matcher_state.get("matcher") or {}).get("resume_keywords") or []),
            "job_keyword_count": len((matcher_state.get("matcher") or {}).get("job_keywords") or []),
            "resume_text_char_count": len(resume_text),
        }
    )
    matcher_state["resume_source_text"] = resume_text
    matcher_state["resume_text_payload"] = text_payload
    return matcher_state, analysis_meta
