"""职业报告的持久化：报告包、版本、快照、反馈与对外展示用的状态。"""

import difflib
import os
import re
import urllib.error
import uuid
from datetime import datetime

from werkzeug.utils import secure_filename

from services.report import empty_report_job, empty_report_state
from services.report.enhancements import CAREER_FEEDBACK_VERSION, normalize_feedback_memory
from services.report.exporters import (
    normalize_br_tags_in_markdown,
    render_report_html,
    render_report_markdown,
)
from services.report.legacy_report import (
    _build_dashboard_summary,
    _build_role_cards,
    _build_role_rankings,
    _normalize_match_output,
    _resolve_effective_match_output,
    _resolve_focus_role_name,
)
from services.user_state import (
    _private_account_directory,
    _read_json_file,
    _write_json_file,
    APP_DATA_LOCK,
    CAREER_REPORT_DIR,
)


def _checked_report_identifier(value, *, allow_empty=False):
    if value is None or value == "":
        if allow_empty:
            return ""
        raise ValueError("缺少报告或快照编号")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("报告或快照编号格式不正确")
    return value


def _career_report_user_dir(username):
    return _private_account_directory(CAREER_REPORT_DIR, username)


CAREER_REPORT_EXPORT_FORMATS = ["pdf", "docx", "md", "html"]


def _career_report_export_formats(raw_formats=None):
    ordered = []
    for item in list(raw_formats or []) + CAREER_REPORT_EXPORT_FORMATS:
        fmt = str(item or "").strip().lower()
        if fmt in {"html", "md", "docx", "pdf"} and fmt not in ordered:
            ordered.append(fmt)
    return ordered or list(CAREER_REPORT_EXPORT_FORMATS)


def _career_report_export_filename_stem(
    title: str,
    *,
    report_id: str = "",
    generated_at: str = "",
    version: str = "",
    snapshot_id: str = "",
) -> str:
    """Build download filename stem (no extension): keep CJK, strip path-forbidden characters."""
    text = str(title or "").strip() or "职业规划报告"
    text = text.replace("\u00b7", "-").replace("・", "-").replace("·", "-")
    text = re.sub(r'[\\/:*?"<>|\r\n\x00]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    extra = []
    ga = str(generated_at or "").strip()
    m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", ga)
    if m:
        extra.append(f"{m.group(1)}{m.group(2)}{m.group(3)}")
    elif str(version or "").strip():
        ver = re.sub(r"[^\w.\-]", "-", str(version))[:24].strip("-")
        if ver:
            extra.append(ver)
    if snapshot_id:
        snap = re.sub(r"[^a-zA-Z0-9._-]", "-", str(snapshot_id))[:24].strip("-")
        if snap:
            extra.append(f"snap-{snap}")
    suffix = ""
    if extra:
        suffix = "_" + "_".join(extra)
    max_text = max(32, 120 - len(suffix))
    if len(text) > max_text:
        text = text[:max_text].rstrip(" .")
    stem = f"{text}{suffix}".strip(" ._")
    if len(stem) > 180:
        stem = stem[:180].rstrip(" .")
    rid = re.sub(r"[^a-zA-Z0-9._-]", "-", str(report_id or ""))[:32].strip("-")
    if not stem or stem in {".", ".."}:
        stem = f"职业规划报告_{rid}" if rid else "职业规划报告"
    return stem


def _attachment_content_disposition(full_filename: str) -> str:
    """ASCII `filename` fallback plus RFC 5987 `filename*` for Unicode download names."""
    safe = secure_filename(full_filename)
    if not safe:
        base, ext = os.path.splitext(full_filename)
        safe = (secure_filename(base) or "career-report") + ext
    encoded = urllib.parse.quote(full_filename, safe="")
    if any(ord(c) > 127 for c in full_filename):
        return f'attachment; filename="{safe}"; filename*=UTF-8\'\'{encoded}'
    return f'attachment; filename="{full_filename}"'


def _career_report_file_paths(username):
    base_dir = _career_report_user_dir(username)
    return {
        "dir": base_dir,
        "json": os.path.join(base_dir, "latest.json"),
        "html": os.path.join(base_dir, "latest.html"),
        "md": os.path.join(base_dir, "latest.md"),
        "job": os.path.join(base_dir, "current_job.json"),
        "versions_dir": os.path.join(base_dir, "versions"),
        "drafts_dir": os.path.join(base_dir, "drafts"),
    }


def _read_career_report_bundle(username):
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        payload = _read_json_file(paths["json"], {})
    return payload if isinstance(payload, dict) else {}


def _read_career_report_bundle_by_id(username, report_id=""):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        if not safe_report_id:
            payload = _read_json_file(paths["json"], {})
            return payload if isinstance(payload, dict) else {}

        archive_path = os.path.join(paths["versions_dir"], f"{safe_report_id}.json")
        if os.path.isfile(archive_path):
            payload = _read_json_file(archive_path, {})
            return payload if isinstance(payload, dict) else {}

        latest = _read_json_file(paths["json"], {})
        latest_id = str((latest.get("meta") or {}).get("report_id") or "").strip()
        if latest_id == safe_report_id:
            return latest if isinstance(latest, dict) else {}
    return {}


def _summarize_career_report_bundle(bundle):
    bundle = _refresh_career_report_role_resolution(bundle)
    if not isinstance(bundle, dict):
        return None

    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    report_id = str(meta.get("report_id") or "").strip()
    if not report_id:
        return None

    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    gap_map = bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {}
    dashboard_summary = document.get("dashboard_summary") if isinstance(document.get("dashboard_summary"), dict) else {}
    evidence_health = document.get("evidence_health") if isinstance(document.get("evidence_health"), dict) else {}
    plan_board = document.get("plan_board") if isinstance(document.get("plan_board"), dict) else {}
    next_actions = document.get("next_actions") if isinstance(document.get("next_actions"), dict) else {}
    match_output = bundle.get("match_output") if isinstance(bundle.get("match_output"), dict) else {}
    focus_role_name = (
        str(document.get("focus_role_name") or "")
        or str(meta.get("focus_role_name") or "")
        or str(gap_map.get("focus_role_name") or "")
    ).strip()
    summary_text = re.sub(
        r"\s+",
        " ",
        str(document.get("executive_summary") or meta.get("summary") or "").strip(),
    )
    fit_score = dashboard_summary.get("fit_score")
    try:
        fit_score = max(0, min(100, int(round(float(fit_score)))))
    except (TypeError, ValueError):
        fit_score = None
    fit_band = str(dashboard_summary.get("fit_band") or match_output.get("fit_band") or "").strip().lower()
    fit_band_label = str(dashboard_summary.get("fit_band_label") or "").strip()
    if not fit_band_label:
        fit_band_label = {
            "strong": "高匹配",
            "moderate": "中等匹配",
            "weak": "低匹配",
            "not_ready": "尚需准备",
        }.get(fit_band, "")

    strengths = evidence_health.get("strengths") if isinstance(evidence_health.get("strengths"), list) else []
    gap_items = []
    for key in ("hard_failures", "skill_gaps", "evidence_gaps", "missing_inputs"):
        values = evidence_health.get(key)
        if isinstance(values, list):
            gap_items.extend(values)
    action_items = plan_board.get("action_items") if isinstance(plan_board.get("action_items"), list) else []
    if not action_items:
        action_items = next_actions.get("action_items") if isinstance(next_actions.get("action_items"), list) else []
    role_cards = document.get("role_cards") if isinstance(document.get("role_cards"), list) else []
    role_rankings = bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else []
    sections = document.get("sections")
    if isinstance(sections, dict):
        section_count = len(sections)
    elif isinstance(sections, list):
        section_count = len(sections)
    else:
        section_count = 0

    return {
        "report_id": report_id,
        "title": str(meta.get("title") or document.get("title") or "职业规划报告").strip() or "职业规划报告",
        "version": str(meta.get("version") or "").strip(),
        "generated_at": str(meta.get("generated_at") or "").strip(),
        "focus_role_id": str(meta.get("focus_role_id") or "").strip(),
        "focus_role_name": focus_role_name,
        "summary_excerpt": summary_text[:117] + "..." if len(summary_text) > 120 else summary_text,
        "fit_score": fit_score,
        "fit_band": fit_band,
        "fit_band_label": fit_band_label,
        "strength_count": len(strengths),
        "gap_count": len(gap_items),
        "action_count": len(action_items),
        "role_count": len(role_cards or role_rankings),
        "section_count": section_count,
    }


def _refresh_career_report_role_resolution(raw_bundle):
    bundle = dict(raw_bundle) if isinstance(raw_bundle, dict) else {}
    meta = dict(bundle.get("meta") or {}) if isinstance(bundle.get("meta"), dict) else {}
    if not meta:
        return bundle

    role_rankings = bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else []
    match_output = bundle.get("match_output") if isinstance(bundle.get("match_output"), dict) else {}
    if not role_rankings or not match_output:
        return bundle

    normalized_match = _normalize_match_output(match_output, role_rankings)
    resolved_match = _resolve_effective_match_output(
        normalized_match,
        role_rankings,
        str(meta.get("focus_role_id") or "").strip(),
    )
    focus_role_name = _resolve_focus_role_name("", role_rankings, resolved_match.get("target_role"))
    if not focus_role_name:
        return bundle

    previous_focus_role_name = str(meta.get("focus_role_name") or "").strip()
    meta["focus_role_name"] = focus_role_name
    title = str(meta.get("title") or "").strip()
    if title and previous_focus_role_name and previous_focus_role_name != focus_role_name:
        meta["title"] = title.replace(previous_focus_role_name, focus_role_name, 1)
    bundle["meta"] = meta
    bundle["match_output"] = resolved_match

    gap_map = dict(bundle.get("gap_map") or {}) if isinstance(bundle.get("gap_map"), dict) else {}
    gap_map["focus_role_name"] = focus_role_name
    bundle["gap_map"] = gap_map

    career_path = dict(bundle.get("career_path") or {}) if isinstance(bundle.get("career_path"), dict) else {}
    if career_path:
        career_path["target_role"] = focus_role_name
        bundle["career_path"] = career_path

    document = dict(bundle.get("report_document") or {}) if isinstance(bundle.get("report_document"), dict) else {}
    if document:
        document_title = str(document.get("title") or "").strip()
        if document_title and previous_focus_role_name and previous_focus_role_name != focus_role_name:
            document["title"] = document_title.replace(previous_focus_role_name, focus_role_name, 1)
        document["focus_role_name"] = focus_role_name
        document["dashboard_summary"] = _build_dashboard_summary(
            focus_role_name,
            resolved_match,
            bundle.get("positioning_output") if isinstance(bundle.get("positioning_output"), dict) else {},
            gap_map,
            bundle.get("resume_evidence") if isinstance(bundle.get("resume_evidence"), dict) else {},
            bundle.get("industry_brief") if isinstance(bundle.get("industry_brief"), dict) else {},
        )
        document["role_cards"] = _build_role_cards(
            role_rankings,
            resolved_match,
            bundle.get("resume_evidence") if isinstance(bundle.get("resume_evidence"), dict) else {},
        )
        bundle["report_document"] = document

    bundle["role_rankings"] = _build_role_rankings(role_rankings, resolved_match)
    return bundle


def _list_career_report_version_summaries(username, include_latest=True, lock=True):
    paths = _career_report_file_paths(username)

    def _collect():
        items = []

        if include_latest:
            latest_bundle = _read_json_file(paths["json"], {})
            summary = _summarize_career_report_bundle(latest_bundle)
            if summary:
                items.append(summary)

        versions_dir = paths["versions_dir"]
        if os.path.isdir(versions_dir):
            for name in os.listdir(versions_dir):
                if not name.lower().endswith(".json"):
                    continue
                payload = _read_json_file(os.path.join(versions_dir, name), {})
                summary = _summarize_career_report_bundle(payload)
                if summary:
                    items.append(summary)

        deduped = []
        seen = set()
        for item in sorted(
            items,
            key=lambda value: (str(value.get("generated_at") or ""), str(value.get("report_id") or "")),
            reverse=True,
        ):
            report_id = str(item.get("report_id") or "").strip()
            if not report_id or report_id in seen:
                continue
            seen.add(report_id)
            deduped.append(item)
        return deduped

    if not lock:
        return _collect()
    with APP_DATA_LOCK:
        return _collect()


def _prepare_career_report_bundle_payload(bundle):
    payload = dict(bundle) if isinstance(bundle, dict) else {}
    report_document = dict(payload.get("report_document") or {}) if isinstance(payload.get("report_document"), dict) else {}
    payload["report_document"] = report_document

    markdown_text = str(report_document.get("markdown") or "").strip()
    if not markdown_text:
        markdown_text = render_report_markdown(payload).strip()
    markdown_text = normalize_br_tags_in_markdown(markdown_text)
    report_document["markdown"] = markdown_text

    html_text = str(report_document.get("html") or "").strip()
    if not html_text:
        html_text = render_report_html(payload).strip()
        report_document["html"] = html_text

    return payload, markdown_text, html_text


def _write_current_career_report_files(paths, payload, markdown_text="", html_text=""):
    _write_json_file(paths["json"], payload)

    if markdown_text:
        with open(paths["md"], "w", encoding="utf-8") as fp:
            fp.write(markdown_text)
    elif os.path.isfile(paths["md"]):
        os.remove(paths["md"])

    if html_text:
        with open(paths["html"], "w", encoding="utf-8") as fp:
            fp.write(html_text)
    elif os.path.isfile(paths["html"]):
        os.remove(paths["html"])

    _write_json_file(paths["job"], {
        "report_id": str(payload.get("meta", {}).get("report_id") or ""),
        "generated_at": str(payload.get("meta", {}).get("generated_at") or ""),
        "title": str(payload.get("meta", {}).get("title") or ""),
    })


def _remove_current_career_report_files(paths):
    for key in ("json", "html", "md", "job"):
        target = paths.get(key)
        if target and os.path.isfile(target):
            os.remove(target)




def _clip_career_report_text(value, limit=140):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[:max(0, limit - 1)]}…"


def _career_report_section_title(section_id, section):
    if not isinstance(section, dict):
        return str(section_id or "章节")
    return str(
        section.get("label")
        or section.get("title")
        or section.get("kicker")
        or section_id
        or "章节"
    ).strip() or "章节"


def _build_career_report_section_map(bundle, markdown_text=""):
    report_document = bundle.get("report_document") if isinstance(bundle, dict) else {}
    report_document = report_document if isinstance(report_document, dict) else {}
    sections = report_document.get("sections")
    result = []
    if isinstance(sections, dict):
        ordered_keys = report_document.get("section_order") or [
            "industry_analysis",
            "career_positioning",
            "resume_evidence",
            "competency_profile",
            "role_match",
            "path_plan",
        ]
        seen = set()
        for key in ordered_keys + list(sections.keys()):
            if key in seen:
                continue
            seen.add(key)
            section = sections.get(key)
            if not isinstance(section, dict):
                continue
            result.append({
                "key": str(key),
                "label": _career_report_section_title(key, section),
                "markdown": str(section.get("markdown") or "").strip(),
            })
        return result
    if isinstance(sections, list):
        for index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue
            result.append({
                "key": str(section.get("id") or f"section-{index + 1}"),
                "label": _career_report_section_title(section.get("id") or f"section-{index + 1}", section),
                "markdown": str(section.get("markdown") or section.get("summary") or "").strip(),
            })
        return result

    source_text = str(markdown_text or report_document.get("markdown") or "").strip()
    if not source_text:
        return []

    current = None
    for raw_line in source_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            if current:
                result.append(current)
            label = line[3:].strip()
            current = {"key": f"section-{len(result) + 1}", "label": label or "章节", "markdown": ""}
            continue
        if current is None:
            continue
        current["markdown"] = f"{current['markdown']}\n{raw_line}".strip()
    if current:
        result.append(current)
    return result


def _normalize_career_report_snapshot(raw_snapshot, bundle=None, report_id=""):
    raw = raw_snapshot if isinstance(raw_snapshot, dict) else {}
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_bundle = bundle if isinstance(bundle, dict) else {}
    meta = base_bundle.get("meta") if isinstance(base_bundle.get("meta"), dict) else {}
    markdown = str(raw.get("markdown") or "").strip()
    normalized = {
        "snapshot_id": str(raw.get("snapshot_id") or f"snapshot-{uuid.uuid4().hex[:10]}").strip(),
        "based_on_report_id": str(raw.get("based_on_report_id") or report_id or meta.get("report_id") or "").strip(),
        "source": str(raw.get("source") or "manual").strip() or "manual",
        "label": str(raw.get("label") or raw.get("title") or "编辑快照").strip() or "编辑快照",
        "title": str(raw.get("title") or raw.get("label") or "编辑快照").strip() or "编辑快照",
        "focus_role_name": str(raw.get("focus_role_name") or meta.get("focus_role_name") or "").strip(),
        "created_at": str(raw.get("created_at") or timestamp).strip(),
        "updated_at": str(raw.get("updated_at") or raw.get("created_at") or timestamp).strip(),
        "markdown": markdown,
        "section_map": raw.get("section_map") if isinstance(raw.get("section_map"), list) else _build_career_report_section_map(base_bundle, markdown),
        "diff_blocks": raw.get("diff_blocks") if isinstance(raw.get("diff_blocks"), list) else [],
        "completeness_check": raw.get("completeness_check") if isinstance(raw.get("completeness_check"), dict) else None,
    }
    normalized["summary"] = str(raw.get("summary") or _clip_career_report_text(markdown, 180)).strip()
    normalized["has_diff"] = bool(normalized["diff_blocks"])
    return normalized


def _public_career_report_snapshot(raw_snapshot, include_content=False):
    snapshot = _normalize_career_report_snapshot(raw_snapshot)
    public_data = {
        "snapshot_id": snapshot["snapshot_id"],
        "based_on_report_id": snapshot["based_on_report_id"],
        "source": snapshot["source"],
        "label": snapshot["label"],
        "title": snapshot["title"],
        "focus_role_name": snapshot["focus_role_name"],
        "created_at": snapshot["created_at"],
        "updated_at": snapshot["updated_at"],
        "summary": snapshot["summary"],
        "has_diff": snapshot["has_diff"],
    }
    if include_content:
        public_data.update({
            "markdown": snapshot["markdown"],
            "section_map": snapshot["section_map"],
            "diff_blocks": snapshot["diff_blocks"],
            "completeness_check": snapshot["completeness_check"],
        })
    return public_data


def _career_report_snapshot_dir(paths, report_id):
    safe_report_id = _checked_report_identifier(report_id)
    return os.path.join(paths["drafts_dir"], safe_report_id)


def _list_career_report_snapshots(username, report_id):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    if not safe_report_id:
        return []
    paths = _career_report_file_paths(username)
    snapshot_dir = _career_report_snapshot_dir(paths, safe_report_id)
    if not os.path.isdir(snapshot_dir):
        return []
    summaries = []
    with APP_DATA_LOCK:
        for name in os.listdir(snapshot_dir):
            if not name.lower().endswith(".json"):
                continue
            payload = _read_json_file(os.path.join(snapshot_dir, name), {})
            if not isinstance(payload, dict):
                continue
            summaries.append(_public_career_report_snapshot(payload))
    summaries.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return summaries


def _read_career_report_snapshot(username, report_id, snapshot_id):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    safe_snapshot_id = _checked_report_identifier(snapshot_id, allow_empty=True)
    if not safe_snapshot_id:
        return None
    paths = _career_report_file_paths(username)
    candidates = []
    if safe_report_id:
        candidates.append(os.path.join(_career_report_snapshot_dir(paths, safe_report_id), f"{safe_snapshot_id}.json"))
    else:
        drafts_root = paths["drafts_dir"]
        if os.path.isdir(drafts_root):
            for child in os.listdir(drafts_root):
                candidates.append(os.path.join(drafts_root, child, f"{safe_snapshot_id}.json"))
    with APP_DATA_LOCK:
        for path in candidates:
            if not os.path.isfile(path):
                continue
            payload = _read_json_file(path, {})
            if isinstance(payload, dict) and payload:
                return payload
    return None


def _commit_career_report_markdown_to_store(username, report_id, markdown_text):
    """将润色后的 Markdown 写回已存储的职业报告正文（阅览室与后续加载同源）。"""
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    md = normalize_br_tags_in_markdown(str(markdown_text or "").strip())
    if not safe_report_id or not md:
        return False
    paths = _career_report_file_paths(username)
    with APP_DATA_LOCK:
        bundle = _read_career_report_bundle_by_id(username, safe_report_id)
        if not isinstance(bundle, dict) or not bundle.get("meta"):
            return False
        report_document = dict(bundle.get("report_document") or {})
        report_document["markdown"] = md
        bundle["report_document"] = report_document
        prepared, md_out, html_out = _prepare_career_report_bundle_payload(bundle)
        latest = _read_json_file(paths["json"], {})
        latest_id = str((latest.get("meta") or {}).get("report_id") or "").strip()
        if latest_id == safe_report_id:
            _write_current_career_report_files(paths, prepared, md_out, html_out)
            return True
        archive_path = os.path.join(paths["versions_dir"], f"{safe_report_id}.json")
        if os.path.isfile(archive_path):
            _write_json_file(archive_path, prepared)
            return True
    return False


def _save_career_report_snapshot(username, report_id, snapshot):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    if not safe_report_id:
        raise ValueError("缺少 report_id")
    paths = _career_report_file_paths(username)
    snapshot_dir = _career_report_snapshot_dir(paths, safe_report_id)
    normalized = _normalize_career_report_snapshot(snapshot, report_id=safe_report_id)
    os.makedirs(snapshot_dir, exist_ok=True)
    target_path = os.path.join(snapshot_dir, f"{normalized['snapshot_id']}.json")
    with APP_DATA_LOCK:
        _write_json_file(target_path, normalized)
    return normalized


_CAREER_REPORT_QUICK_POLISH = {
    "professional": "请将目标段落改写为更专业、偏职场与学术书面语的表达；保持事实与结论不变，不新增数据或承诺。",
    "concise": "请在保留关键信息的前提下删除冗余与重复表述，使行文更精炼。",
    "bullets": "请将段落改写为条理清晰的项目符号或编号要点（使用 Markdown 列表语法），便于扫读。",
    "evidence": "请在不杜撰量化数据的前提下强化论据：突出能力、经历与岗位/行业要求之间的对应关系。",
}


def _fallback_summary_career_quick_action(key: str) -> str:
    return {
        "professional": "已按「更专业」收紧措辞与论证语气，使之更符合职业报告书面表达；未新增事实。",
        "concise": "已删减重复表述并压缩句子，使信息更集中；关键结论未改。",
        "bullets": "已将段落改写为要点列表，便于快速扫读；原意保持不变。",
        "evidence": "已强化论点与经历、岗位之间的对应表述；未虚构数据。",
    }.get(key, "已完成本次润色，请对照 Diff 查看具体改动。")


def _split_career_polish_output(raw: str):
    """模型输出：先概括，再一行 <<<AI_BODY>>>，再润色正文。无标记时返回 ("", "")。"""
    s = str(raw or "").strip()
    mark = "<<<AI_BODY>>>"
    if mark not in s:
        return "", ""
    head, tail = s.split(mark, 1)
    body = tail.strip()
    summary = head.strip()
    if body:
        return summary, body
    return "", ""


def _build_career_report_diff_blocks(original_text, proposed_text):
    original_lines = str(original_text or "").splitlines()
    proposed_lines = str(proposed_text or "").splitlines()
    matcher = difflib.SequenceMatcher(a=original_lines, b=proposed_lines)
    blocks = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace":
            if i1 != i2:
                blocks.append({"type": "delete", "lines": original_lines[i1:i2]})
            if j1 != j2:
                blocks.append({"type": "add", "lines": proposed_lines[j1:j2]})
            continue
        blocks.append({
            "type": "equal" if tag == "equal" else ("delete" if tag == "delete" else "add"),
            "lines": original_lines[i1:i2] if tag != "insert" else proposed_lines[j1:j2],
        })
    return [block for block in blocks if block.get("lines")]


def _run_career_report_completeness_check(bundle, markdown_text="", snapshot=None):
    safe_bundle = bundle if isinstance(bundle, dict) else {}
    report_document = safe_bundle.get("report_document") if isinstance(safe_bundle.get("report_document"), dict) else {}
    section_map = []
    if isinstance(snapshot, dict) and isinstance(snapshot.get("section_map"), list):
        section_map = snapshot.get("section_map") or []
    if not section_map:
        section_map = _build_career_report_section_map(safe_bundle, markdown_text)
    issues = []

    required_sections = {
        "industry_analysis": "行业现状",
        "career_positioning": "当前定位",
        "role_match": "目标岗位对比",
        "path_plan": "职业路径",
    }
    if report_document.get("reading_layout") in {"narrative-v1", "narrative-v2", "numbered-reader-v3"}:
        required_sections = {"executive_summary": "核心结论", "personal_traits": "简历分析",
                             "matching_decision": "岗位对照", "gap_action_plan": "成长规划",
                             "development_path": "总结与下一步", "appendix": "参考依据"}
    elif report_document.get("section_order"):
        required_sections = {"personal_traits": "个人画像", "target_job_analysis": "职业目标", "macro_environment": "就业市场",
                             "matching_decision": "岗位适配", "ability_gaps": "能力差距", "development_path": "成长路径",
                             "gap_action_plan": "行动计划", "risk_backup": "动态评估", "appendix": "参考依据"}
    section_keys = {str(item.get("key") or "").strip() for item in section_map if isinstance(item, dict)}
    for key, label in required_sections.items():
        if key not in section_keys or not any(item.get("key") == key and item.get("markdown") for item in section_map):
            issues.append({"level": "warning", "type": "missing_section", "message": f"缺少“{label}”章节。"})

    markdown_value = str(markdown_text or report_document.get("markdown") or "").strip()
    if report_document.get("reading_layout") not in {"narrative-v1", "narrative-v2", "numbered-reader-v3"} and len(markdown_value) < 600:
        issues.append({"level": "warning", "type": "content_length", "message": "报告正文偏短，请检查关键判断、依据和行动安排是否完整。"})

    explainability_summary = report_document.get("explainability_summary") if isinstance(report_document.get("explainability_summary"), dict) else {}
    because_items = explainability_summary.get("headline_because") if isinstance(explainability_summary.get("headline_because"), list) else []
    evidence_items = []
    if isinstance(snapshot, dict):
        completeness = snapshot.get("completeness_check")
        if isinstance(completeness, dict):
            evidence_items = completeness.get("evidence_trace") if isinstance(completeness.get("evidence_trace"), list) else []
    if not evidence_items:
        evidence_health = report_document.get("evidence_health") if isinstance(report_document.get("evidence_health"), dict) else {}
        evidence_items = evidence_health.get("evidence_trace") if isinstance(evidence_health.get("evidence_trace"), list) else []

    if not because_items:
        issues.append({"level": "warning", "type": "explainability", "message": "关键判断缺少“为什么”的解释链。"})
    if not evidence_items:
        issues.append({"level": "warning", "type": "evidence_trace", "message": "当前报告缺少简历证据回指，用户很难验证判断来源。"})

    plan_board = report_document.get("plan_board") if isinstance(report_document.get("plan_board"), dict) else {}
    action_items = plan_board.get("action_items") if isinstance(plan_board.get("action_items"), list) else []
    if not action_items:
        next_actions = report_document.get("next_actions") if isinstance(report_document.get("next_actions"), dict) else {}
        action_items = next_actions.get("action_items") if isinstance(next_actions.get("action_items"), list) else []
    if not action_items:
        issues.append({"level": "warning", "type": "action_plan", "message": "行动计划为空，无法形成从差距到执行的闭环。"})

    return {
        "status": "pass" if not issues else "attention",
        "issue_count": len(issues),
        "issues": issues,
        "section_count": len(section_map),
        "markdown_chars": len(markdown_value),
        "headline_because": because_items[:4],
        "evidence_trace": evidence_items[:4],
    }




def _normalize_career_report_feedback(raw_feedback):
    return normalize_feedback_memory(raw_feedback)


def _append_career_report_feedback(raw_feedback, entry):
    normalized = _normalize_career_report_feedback(raw_feedback)
    entries = normalized.get("entries") if isinstance(normalized.get("entries"), list) else []
    entries.append(
        {
            "id": str(entry.get("id") or f"feedback-{uuid.uuid4().hex[:10]}").strip(),
            "report_id": str(entry.get("report_id") or "").strip(),
            "focus_role_id": str(entry.get("focus_role_id") or "").strip(),
            "focus_role_name": str(entry.get("focus_role_name") or "").strip(),
            "verdict": str(entry.get("verdict") or "partial").strip().lower(),
            "note": str(entry.get("note") or "").strip()[:320],
            "created_at": str(entry.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")).strip(),
        }
    )
    return _normalize_career_report_feedback({
        "version": CAREER_FEEDBACK_VERSION,
        "entries": entries,
    })


def _public_career_report_state(raw_state):
    state = empty_report_state()
    if isinstance(raw_state, dict):
        state.update({
            "status": str(raw_state.get("status") or state["status"]),
            "job_id": str(raw_state.get("job_id") or ""),
            "report_id": str(raw_state.get("report_id") or ""),
            "generated_at": str(raw_state.get("generated_at") or ""),
            "stage": str(raw_state.get("stage") or ""),
            "stage_label": str(raw_state.get("stage_label") or ""),
            "stage_detail": str(raw_state.get("stage_detail") or ""),
            "error_message": str(raw_state.get("error_message") or ""),
            "progress": raw_state.get("progress") if isinstance(raw_state.get("progress"), list) else [],
            "agent_activity": raw_state.get("agent_activity") if isinstance(raw_state.get("agent_activity"), dict) else {},
            "model": str(raw_state.get("model") or ""),
            "generation_mode": str(raw_state.get("generation_mode") or ""),
            "focus_role_id": str(raw_state.get("focus_role_id") or ""),
            "title": str(raw_state.get("title") or ""),
            "summary": str(raw_state.get("summary") or ""),
            "export_formats": _career_report_export_formats(raw_state.get("export_formats")),
            "tracker": raw_state.get("tracker") if isinstance(raw_state.get("tracker"), dict) else None,
            "feedback": _normalize_career_report_feedback(raw_state.get("feedback")),
        })
    return state


def _sanitize_transient_career_report_state(username, raw_state, current_bundle=None):
    state = raw_state if isinstance(raw_state, dict) else {}
    status = str(state.get("status") or "").strip().lower()
    if status not in {"canceled", "cancelled"}:
        return state, False

    bundle = current_bundle if isinstance(current_bundle, dict) else _read_career_report_bundle(username)
    if isinstance(bundle, dict) and bundle.get("meta"):
        return state, False

    cleaned = empty_report_state()
    feedback = _normalize_career_report_feedback(state.get("feedback"))
    if feedback is not None:
        cleaned["feedback"] = feedback
    return cleaned, True


def _public_career_report_job(raw_job):
    job = empty_report_job()
    if isinstance(raw_job, dict):
        job.update({
            "job_id": str(raw_job.get("job_id") or ""),
            "username": str(raw_job.get("username") or ""),
            "status": str(raw_job.get("status") or job["status"]),
            "stage": str(raw_job.get("stage") or ""),
            "stage_label": str(raw_job.get("stage_label") or ""),
            "stage_detail": str(raw_job.get("stage_detail") or ""),
            "message": str(raw_job.get("message") or ""),
            "created_at": int(raw_job.get("created_at") or 0),
            "started_at": int(raw_job.get("started_at") or 0),
            "finished_at": int(raw_job.get("finished_at") or 0),
            "report_id": str(raw_job.get("report_id") or ""),
            "progress": raw_job.get("progress") if isinstance(raw_job.get("progress"), list) else [],
            "agent_activity": raw_job.get("agent_activity") if isinstance(raw_job.get("agent_activity"), dict) else {},
            "model": str(raw_job.get("model") or ""),
            "generation_mode": str(raw_job.get("generation_mode") or ""),
        })
    return job


def _public_career_report_bundle(raw_bundle):
    bundle = _refresh_career_report_role_resolution(raw_bundle)
    bundle = bundle if isinstance(bundle, dict) else {}
    meta = bundle.get("meta") if isinstance(bundle.get("meta"), dict) else {}
    document = bundle.get("report_document") if isinstance(bundle.get("report_document"), dict) else {}
    public_document = dict(document)
    public_document.pop("markdown", None)
    public_document.pop("html", None)
    report_id = str(meta.get("report_id") or "").strip()
    return {
        "meta": meta,
        "industry_brief": bundle.get("industry_brief") if isinstance(bundle.get("industry_brief"), dict) else {},
        "positioning_output": bundle.get("positioning_output") if isinstance(bundle.get("positioning_output"), dict) else {},
        "resume_evidence": bundle.get("resume_evidence") if isinstance(bundle.get("resume_evidence"), dict) else {},
        "competency_profile": bundle.get("competency_profile") if isinstance(bundle.get("competency_profile"), dict) else {},
        "match_output": bundle.get("match_output") if isinstance(bundle.get("match_output"), dict) else {},
        "path_plan": bundle.get("path_plan") if isinstance(bundle.get("path_plan"), dict) else {},
        "profile_snapshot": bundle.get("profile_snapshot") if isinstance(bundle.get("profile_snapshot"), dict) else {},
        "role_rankings": bundle.get("role_rankings") if isinstance(bundle.get("role_rankings"), list) else [],
        "gap_map": bundle.get("gap_map") if isinstance(bundle.get("gap_map"), dict) else {},
        "career_path": bundle.get("career_path") if isinstance(bundle.get("career_path"), dict) else {},
        "phase_plan": bundle.get("phase_plan") if isinstance(bundle.get("phase_plan"), dict) else {},
        "trend_brief": bundle.get("trend_brief") if isinstance(bundle.get("trend_brief"), dict) else {},
        "report_document": public_document,
        "draft_snapshots": _list_career_report_snapshots(meta.get("username") or meta.get("user") or "", report_id) if report_id and (meta.get("username") or meta.get("user")) else [],
        "generation_diagnostics": bundle.get("generation_diagnostics") if isinstance(bundle.get("generation_diagnostics"), dict) else {},
    }
