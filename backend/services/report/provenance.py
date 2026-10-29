"""固定报告的输入与代码版本；元数据只记录内容摘要，不记录模型凭证。"""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from ..paths import PROJECT_ROOT
from .schemas import REPORT_VERSION


def content_revision(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def freeze_profile(profile):
    # agent_memory 内可能再次引用画像本身；只保留报告原本对外展示的画像字段。
    return deepcopy({key: value for key, value in (profile or {}).items()
                     if key not in {"agent_memory", "agent_workflow"}})


def capture_provenance(inputs, profile, model_name):
    prompt_dir = PROJECT_ROOT / "experiments" / "news_advisor" / "prompt"
    prompts = {path.stem: sha256(path.read_bytes()).hexdigest()
               for path in sorted(prompt_dir.glob("*.py")) if path.name != "__init__.py"}
    workflow = PROJECT_ROOT / "experiments" / "news_advisor" / "report_workflow.py"
    return {
        "captured_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "report_version": REPORT_VERSION, "initial_model": model_name,
        "input_revision": content_revision(inputs), "profile_revision": content_revision(profile),
        "profile_scope": "display_context_only",
        "resume_revision": content_revision(inputs["raw_resume"]),
        "prompt_revisions": prompts, "workflow_revision": sha256(workflow.read_bytes()).hexdigest(),
        "component_revisions": {
            path.relative_to(PROJECT_ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted((PROJECT_ROOT / "experiments" / "news_advisor").rglob("*.py"))
        },
    }


def report_provenance(state):
    result = deepcopy(state.get("provenance", {}))
    result["snapshot_status"] = "frozen" if "profile_snapshot" in state else "legacy_unavailable"
    # 原始输入和最终补充回答分开记版本，便于复现修订前后的判断。
    result["decision_revision"] = content_revision(state.get("decision_input", {}))
    result["review_revision"] = content_revision(state.get("review", {}))
    result["job_source_revisions"] = [
        {"target_id": target["target_id"], "revision": content_revision(target["job_analysis"].get("sources", []))}
        for target in state.get("results", {}).get("job_analysis", {}).get("data", {}).get("targets", [])
    ]
    return result
