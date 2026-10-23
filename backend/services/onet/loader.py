"""
O*NET 30.2 Database Loader — career report enrichment.
Provides lazy-loaded, cached access to O*NET occupational data.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Optional

from ..paths import ONET_DB_DIR

# Internal role ID → O*NET SOC Code
ROLE_TO_SOC: dict[str, str] = {
    "java_backend":      "15-1252.00",
    "product_manager":   "15-1255.01",
    "data_analyst":      "15-2051.01",
    "new_media_ops":     "27-3099.00",
    "hr_specialist":     "13-1071.00",
    "sales_trainee":     "41-3091.00",
    "uiux_designer":     "27-1024.00",
    "finance_audit":     "13-2011.00",
    "project_assistant": "13-1082.00",
    "content_editor":    "27-3043.00",
}

JOB_ZONE_LABELS: dict[int, str] = {
    1: "无需特定学历准备",
    2: "高中至大专水平",
    3: "通常需要本科学历",
    4: "本科及以上，通常需要工作经验",
    5: "通常需要研究生学历",
}

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {}


def _df(filename: str) -> Optional[Any]:
    """Lazily load and thread-safely cache an O*NET Excel file."""
    try:
        import pandas as pd
    except ImportError:
        return None
    with _LOCK:
        if filename in _CACHE:
            return _CACHE[filename]
        path = os.path.join(ONET_DB_DIR, filename)
        if not os.path.isfile(path):
            _CACHE[filename] = None
            return None
        try:
            frame = pd.read_excel(path)
            _CACHE[filename] = frame
            return frame
        except Exception:
            _CACHE[filename] = None
            return None


def get_occupation_info(soc_code: str) -> dict[str, str]:
    """Return title and description for a SOC code."""
    df = _df("Occupation Data.xlsx")
    if df is None:
        return {}
    prefix = soc_code[:7]
    rows = df[df["O*NET-SOC Code"].astype(str).str.startswith(prefix)]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {
        "title": str(row.get("Title", "")),
        "description": str(row.get("Description", "")),
    }


def get_related_occupations(soc_code: str, limit: int = 6) -> list[dict[str, str]]:
    """Return related occupations (ordered by Index/similarity) for career path context."""
    df = _df("Related Occupations.xlsx")
    if df is None:
        return []
    prefix = soc_code[:7]
    rows = df[df["O*NET-SOC Code"].astype(str).str.startswith(prefix)]
    # Prefer Primary-Short tier
    primary = rows[rows["Relatedness Tier"].astype(str) == "Primary-Short"]
    if not primary.empty:
        rows = primary
    if "Index" in rows.columns:
        rows = rows.sort_values("Index")
    result = []
    for _, row in rows.head(limit).iterrows():
        result.append({
            "soc_code": str(row.get("Related O*NET-SOC Code", "")),
            "title": str(row.get("Related Title", "")),
        })
    return result


def get_top_skills(soc_code: str, limit: int = 8) -> list[str]:
    """Return top skills (by Importance) for a SOC code."""
    df = _df("Skills.xlsx")
    if df is None:
        return []
    prefix = soc_code[:7]
    rows = df[df["O*NET-SOC Code"].astype(str).str.startswith(prefix)]
    rows = rows[rows["Scale ID"] == "IM"]
    rows = rows.sort_values("Data Value", ascending=False)
    seen: list[str] = []
    for _, row in rows.iterrows():
        skill = str(row.get("Element Name", "")).strip()
        if skill and skill not in seen:
            seen.append(skill)
            if len(seen) >= limit:
                break
    return seen


def get_job_zone(soc_code: str) -> Optional[int]:
    """Return job zone (1-5) for a SOC code."""
    df = _df("Job Zones.xlsx")
    if df is None:
        return None
    prefix = soc_code[:7]
    rows = df[df["O*NET-SOC Code"].astype(str).str.startswith(prefix)]
    if rows.empty:
        return None
    try:
        return int(rows.iloc[0]["Job Zone"])
    except Exception:
        return None


def enrich_role(role_id: str) -> dict[str, Any]:
    """Return all available O*NET enrichment data for a role ID."""
    soc_code = ROLE_TO_SOC.get(str(role_id or ""))
    if not soc_code:
        return {}
    result: dict[str, Any] = {"soc_code": soc_code}
    occ = get_occupation_info(soc_code)
    result.update(occ)
    skills = get_top_skills(soc_code, 6)
    if skills:
        result["onet_skills"] = skills
    related = get_related_occupations(soc_code, 5)
    if related:
        result["related_occupations"] = related
    job_zone = get_job_zone(soc_code)
    if job_zone is not None:
        result["job_zone"] = job_zone
        result["job_zone_label"] = JOB_ZONE_LABELS.get(job_zone, f"Job Zone {job_zone}")
    return result
