"""写入类操作：保存报告包、删除报告版本，并同步行动追踪状态。"""

import os
import shutil
from datetime import datetime

from services.report import empty_report_state
from services.report.store import (
    _career_report_file_paths,
    _career_report_snapshot_dir,
    _checked_report_identifier,
    _prepare_career_report_bundle_payload,
    _read_career_report_bundle,
    _remove_current_career_report_files,
    _summarize_career_report_bundle,
    _write_current_career_report_files,
)
from services.report.tracker import _sync_career_report_tracker_state
from services.user_state import (
    APP_DATA_LOCK,
    _load_user_state,
    _read_json_file,
    _save_user_state,
    _write_json_file,
)


def _save_career_report_bundle(username, bundle):
    paths = _career_report_file_paths(username)
    os.makedirs(paths["dir"], exist_ok=True)
    payload, markdown_text, html_text = _prepare_career_report_bundle_payload(bundle)
    new_meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    new_report_id = str(new_meta.get("report_id") or "").strip()
    versions_dir = paths["versions_dir"]
    with APP_DATA_LOCK:
        existing = _read_json_file(paths["json"], {})
        if (
            isinstance(existing, dict)
            and existing.get("meta")
            and new_report_id
            and isinstance(existing.get("meta"), dict)
        ):
            old_id = str(existing["meta"].get("report_id") or "").strip()
            if old_id and old_id != new_report_id and existing.get("report_document"):
                os.makedirs(versions_dir, exist_ok=True)
                archive_path = os.path.join(versions_dir, f"{old_id}.json")
                if not os.path.isfile(archive_path):
                    _write_json_file(archive_path, existing)
        _write_current_career_report_files(paths, payload, markdown_text, html_text)
    state = _load_user_state(username)
    profile_snapshot = payload.get("profile_snapshot") if isinstance(payload.get("profile_snapshot"), dict) else {}
    if profile_snapshot:
        state["profile_snapshot"] = {
            "version": "2026.04-profile-snapshot-v1",
            "updated_at": str(new_meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "profile": profile_snapshot,
            "source": "career_report_bundle",
        }
    role_rankings = payload.get("role_rankings") if isinstance(payload.get("role_rankings"), list) else []
    if role_rankings:
        matching_state = state.get("career_matching") if isinstance(state.get("career_matching"), dict) else {}
        focus_role_id = str(new_meta.get("focus_role_id") or matching_state.get("focus_role_id") or "").strip()
        focus_role_name = str(new_meta.get("focus_role_name") or matching_state.get("focus_role_name") or "").strip()
        matched_focus_role = next((role for role in role_rankings if str(role.get("id") or "").strip() == focus_role_id), None)
        if focus_role_name and matched_focus_role and str(matched_focus_role.get("name") or "").strip() != focus_role_name:
            matched_focus_role = next((role for role in role_rankings if str(role.get("name") or "").strip() == focus_role_name), None)
        if not matched_focus_role and focus_role_name:
            matched_focus_role = next((role for role in role_rankings if str(role.get("name") or "").strip() == focus_role_name), None)
        if not matched_focus_role and role_rankings:
            matched_focus_role = role_rankings[0] if isinstance(role_rankings[0], dict) else None
        if isinstance(matched_focus_role, dict):
            focus_role_id = str(matched_focus_role.get("id") or focus_role_id or "").strip()
            focus_role_name = str(matched_focus_role.get("name") or focus_role_name or "").strip()
        matching_state.update(
            {
                "version": "2026.04-career-matching-v1",
                "updated_at": str(new_meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                "focus_role_id": focus_role_id,
                "focus_role_name": focus_role_name,
                "role_rankings": role_rankings,
                "source": "career_report_bundle",
            }
        )
        state["career_matching"] = matching_state
    diagnostics = payload.get("generation_diagnostics") if isinstance(payload.get("generation_diagnostics"), dict) else {}
    news_snapshot = diagnostics.get("news_context_snapshot") if isinstance(diagnostics.get("news_context_snapshot"), dict) else {}
    if news_snapshot:
        state["news_context"] = {
            "version": "2026.04-news-context-v1",
            "updated_at": str(new_meta.get("generated_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "report_id": str(new_meta.get("report_id") or "").strip(),
            "item_count": int(news_snapshot.get("item_count") or 0),
            "char_count": int(news_snapshot.get("char_count") or 0),
            "source": str(news_snapshot.get("source") or "career_report_bundle").strip(),
            "text": str(news_snapshot.get("text") or ""),
        }
    _save_user_state(username, state)
    return payload


def _delete_career_report_version(username, report_id):
    safe_report_id = _checked_report_identifier(report_id, allow_empty=True)
    if not safe_report_id:
        raise ValueError("缺少 report_id")

    paths = _career_report_file_paths(username)
    deleted_current = False
    replacement_report_id = ""
    replacement_title = ""

    with APP_DATA_LOCK:
        latest_bundle = _read_json_file(paths["json"], {})
        latest_id = str((latest_bundle.get("meta") or {}).get("report_id") or "").strip()
        archive_path = os.path.join(paths["versions_dir"], f"{safe_report_id}.json")

        if latest_id == safe_report_id:
            deleted_current = True
            replacement_candidates = []
            if os.path.isdir(paths["versions_dir"]):
                for name in os.listdir(paths["versions_dir"]):
                    if not name.lower().endswith(".json"):
                        continue
                    candidate_path = os.path.join(paths["versions_dir"], name)
                    payload = _read_json_file(candidate_path, {})
                    summary = _summarize_career_report_bundle(payload)
                    if summary:
                        replacement_candidates.append((summary, payload, candidate_path))

            replacement_candidates.sort(
                key=lambda item: (str(item[0].get("generated_at") or ""), str(item[0].get("report_id") or "")),
                reverse=True,
            )

            if replacement_candidates:
                summary, replacement_bundle, replacement_path = replacement_candidates[0]
                replacement_report_id = str(summary.get("report_id") or "").strip()
                replacement_title = str(summary.get("title") or "").strip()
                if os.path.isfile(replacement_path):
                    os.remove(replacement_path)
                prepared_bundle, markdown_text, html_text = _prepare_career_report_bundle_payload(replacement_bundle)
                _write_current_career_report_files(paths, prepared_bundle, markdown_text, html_text)
            else:
                _remove_current_career_report_files(paths)
        elif os.path.isfile(archive_path):
            os.remove(archive_path)
        else:
            raise FileNotFoundError("未找到对应的职业报告版本。")

        snapshot_dir = _career_report_snapshot_dir(paths, safe_report_id)
        if os.path.isdir(snapshot_dir):
            shutil.rmtree(snapshot_dir, ignore_errors=True)

    current_bundle = _read_career_report_bundle(username)
    if isinstance(current_bundle, dict) and current_bundle.get("meta"):
        _sync_career_report_tracker_state(username, current_bundle)
    else:
        state = _load_user_state(username)
        state["career_report"] = empty_report_state()
        _save_user_state(username, state)

    return {
        "deleted_current": deleted_current,
        "deleted_report_id": safe_report_id,
        "replacement_report_id": replacement_report_id,
        "replacement_title": replacement_title,
    }
