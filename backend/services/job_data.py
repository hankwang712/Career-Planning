"""各城市岗位样本数据：读取、补充数据合并、摘要与详情接口。"""
import json
import logging
import os
import threading

from flask import Blueprint, jsonify, request

from .paths import DATA_DIR

logger = logging.getLogger(__name__)

BOSS_INFO_DIR = os.path.join(DATA_DIR, "jobs")

OTHER_CITY_BOSS_JOBS_FILE = os.path.join(DATA_DIR, "cleaned", "other_city_boss_format.json")

# 仅出现在补充数据中的城市：样本数低于该阈值的不进入下拉列表，避免一次性加载过多城市拖慢 bootstrap。
SUPPLEMENT_EXTRA_CITY_MIN_JOBS = int(os.environ.get("SUPPLEMENT_EXTRA_CITY_MIN_JOBS", "5"))

JOB_CACHE_LOCK = threading.Lock()

JOB_FILE_CACHE = {}

SUPPLEMENT_JOBS_CACHE = {"signature": None, "by_city": None}

JOB_CACHE_MAX_AGE_SECONDS = 900

JOB_DETAIL_ONLY_FIELDS = {
    "岗位描述",
    "公司简介",
    "公司福利",
}


def list_city_files():
    if not os.path.isdir(BOSS_INFO_DIR):
        return []
    return sorted(f for f in os.listdir(BOSS_INFO_DIR) if f.endswith(".json"))


def other_city_jobs_file_signature():
    """用于缓存失效：补充岗位文件不存在时返回稳定占位签名。"""
    if not os.path.isfile(OTHER_CITY_BOSS_JOBS_FILE):
        return ("missing", 0, 0)
    stat = os.stat(OTHER_CITY_BOSS_JOBS_FILE)
    return ("ok", stat.st_mtime_ns, stat.st_size)


def load_supplement_jobs_by_city():
    """读取 other_city 清洗结果，按城市分组；整文件解析结果带签名缓存。"""
    sig = other_city_jobs_file_signature()
    with JOB_CACHE_LOCK:
        if SUPPLEMENT_JOBS_CACHE.get("signature") == sig and SUPPLEMENT_JOBS_CACHE.get("by_city") is not None:
            return SUPPLEMENT_JOBS_CACHE["by_city"]
    if sig[0] == "missing":
        empty = {}
        with JOB_CACHE_LOCK:
            SUPPLEMENT_JOBS_CACHE["signature"] = sig
            SUPPLEMENT_JOBS_CACHE["by_city"] = empty
        return empty
    try:
        with open(OTHER_CITY_BOSS_JOBS_FILE, "r", encoding="utf-8") as fp:
            all_jobs = json.load(fp)
    except Exception as exc:
        logger.warning("读取补充岗位文件失败 %s：%s", OTHER_CITY_BOSS_JOBS_FILE, exc)
        empty = {}
        with JOB_CACHE_LOCK:
            SUPPLEMENT_JOBS_CACHE["signature"] = sig
            SUPPLEMENT_JOBS_CACHE["by_city"] = empty
        return empty
    if not isinstance(all_jobs, list):
        all_jobs = []
    by_city = {}
    for job in all_jobs:
        if not isinstance(job, dict):
            continue
        c = str(job.get("城市") or job.get("采集城市") or "").strip()
        if not c:
            continue
        by_city.setdefault(c, []).append(job)
    with JOB_CACHE_LOCK:
        SUPPLEMENT_JOBS_CACHE["signature"] = sig
        SUPPLEMENT_JOBS_CACHE["by_city"] = by_city
    return by_city


def merge_job_records_dedupe(base_jobs, extra_jobs):
    """合并 boss 与补充数据，按公司与岗位等简单指纹去重。

    返回值第二项为「来自补充文件且未被指纹判重剔除」的条数，用于前端标注热门城市。
    """
    seen = set()
    out = []
    supplement_appended = 0

    def fingerprint(job):
        if not isinstance(job, dict):
            return None
        return (
            str(job.get("公司名称") or ""),
            str(job.get("岗位名称") or ""),
            str(job.get("薪资") or ""),
            str(job.get("城市") or job.get("采集城市") or ""),
        )

    for job in base_jobs or []:
        fp = fingerprint(job)
        if fp is None or fp in seen:
            continue
        seen.add(fp)
        out.append(job)
    for job in extra_jobs or []:
        fp = fingerprint(job)
        if fp is None or fp in seen:
            continue
        seen.add(fp)
        out.append(job)
        supplement_appended += 1
    return out, supplement_appended


def list_job_cities():
    """岗位 API 使用的城市列表：boss_info 文件名 + 补充数据中样本足够的非重复城市。"""
    base = [fname[:-5] for fname in list_city_files()]
    base_set = set(base)
    try:
        supplement = load_supplement_jobs_by_city()
    except Exception as exc:
        logger.warning("分组补充岗位数据失败：%s", exc)
        supplement = {}
    extra = [
        name
        for name, rows in supplement.items()
        if rows and name not in base_set and len(rows) >= SUPPLEMENT_EXTRA_CITY_MIN_JOBS
    ]
    return sorted(set(base) | set(extra))


def job_id(city, index):
    return f"{city}:{index}"


def cache_json_response(payload, max_age=JOB_CACHE_MAX_AGE_SECONDS, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = f"public, max-age={max_age}"
    return response


def get_city_cache_entry(city):
    city_name = str(city or "").strip()
    if not city_name:
        raise FileNotFoundError("city is required")

    fname = f"{city_name}.json"
    fpath = os.path.join(BOSS_INFO_DIR, fname)
    boss_exists = os.path.isfile(fpath)
    supplement_sig = other_city_jobs_file_signature()
    supplement_by_city = load_supplement_jobs_by_city()
    supplement_rows = supplement_by_city.get(city_name, [])

    if not boss_exists and not supplement_rows:
        raise FileNotFoundError(fname)

    boss_sig = None
    if boss_exists:
        stat = os.stat(fpath)
        boss_sig = (stat.st_mtime_ns, stat.st_size)
    combined_signature = (city_name, boss_sig, supplement_sig)

    with JOB_CACHE_LOCK:
        cached = JOB_FILE_CACHE.get(city_name)
        if cached and cached.get("signature") == combined_signature:
            return cached

    jobs_boss = []
    if boss_exists:
        with open(fpath, "r", encoding="utf-8") as fp:
            jobs_boss = json.load(fp)
        if not isinstance(jobs_boss, list):
            jobs_boss = []

    jobs, supplement_added = merge_job_records_dedupe(jobs_boss, supplement_rows)

    entry = {
        "signature": combined_signature,
        "jobs": jobs,
        "summaries": None,
        "supplement_added_count": supplement_added,
    }
    with JOB_CACHE_LOCK:
        JOB_FILE_CACHE[city_name] = entry
    return entry


def summarize_job(job, city, index):
    summary = {
        key: value
        for key, value in job.items()
        if key not in JOB_DETAIL_ONLY_FIELDS
    }
    summary["job_id"] = job_id(city, index)
    return summary


def get_city_job_summaries(city):
    entry = get_city_cache_entry(city)
    if entry.get("summaries") is None:
        entry["summaries"] = [
            summarize_job(job, city, index)
            for index, job in enumerate(entry["jobs"])
        ]
    return entry["summaries"]


def get_city_job_detail(city, index):
    entry = get_city_cache_entry(city)
    if index < 0 or index >= len(entry["jobs"]):
        raise IndexError(index)
    detail = dict(entry["jobs"][index])
    detail["job_id"] = job_id(city, index)
    return detail


def jobs_bootstrap_payload():
    """聚合 bootstrap 岗位摘要，并附带 boss_info 城市列表与补充数据热度信息。"""
    cities = list_job_cities()
    boss_cities = [fname[:-5] for fname in list_city_files()]
    jobs = []
    city_supplement_extra_count = {}
    boss_city_set = set(boss_cities)
    for city_name in cities:
        try:
            summaries = get_city_job_summaries(city_name)
            jobs.extend(summaries)
            if city_name in boss_city_set:
                entry = get_city_cache_entry(city_name)
                n = int(entry.get("supplement_added_count") or 0)
                if n > 0:
                    city_supplement_extra_count[city_name] = n
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning("读取 %s 失败：%s", city_name, exc)
    return {
        "cities": cities,
        "boss_cities": boss_cities,
        "city_supplement_extra_count": city_supplement_extra_count,
        "jobs": jobs,
    }


def create_blueprint():
    blueprint = Blueprint("job_data", __name__)

    @blueprint.route("/api/cities")
    def api_cities():
        cities = list_job_cities()
        return cache_json_response(cities, max_age=3600)

    @blueprint.route("/api/jobs/bootstrap")
    def api_jobs_bootstrap():
        """Return cities and job summaries in one payload for bootstrap usage."""
        return cache_json_response(jobs_bootstrap_payload())

    # API：岗位数据
    @blueprint.route("/api/jobs")
    def api_jobs():
        city = str(request.args.get("city", "all") or "all").strip() or "all"
        view = str(request.args.get("view", "full") or "full").strip().lower()
        if view == "bootstrap":
            return cache_json_response(jobs_bootstrap_payload())
        jobs = []

        cities = list_job_cities() if city == "all" else [city]

        for city_name in cities:
            try:
                if view == "summary":
                    jobs.extend(get_city_job_summaries(city_name))
                else:
                    city_jobs = get_city_cache_entry(city_name)["jobs"]
                    jobs.extend(
                        {
                            **job,
                            "job_id": job_id(city_name, index),
                        }
                        for index, job in enumerate(city_jobs)
                    )
            except FileNotFoundError:
                continue
            except Exception as exc:
                logger.warning("读取 %s 失败：%s", city_name, exc)

        return cache_json_response(jobs)

    @blueprint.route("/api/job-detail")
    def api_job_detail():
        raw_job_id = str(request.args.get("id", "") or "").strip()
        if ":" not in raw_job_id:
            return cache_json_response({"message": "job id 缺失或格式错误"}, status=400)

        city_name, index_text = raw_job_id.split(":", 1)
        try:
            detail = get_city_job_detail(city_name, int(index_text))
        except (TypeError, ValueError):
            return cache_json_response({"message": "job id 参数格式错误"}, status=400)
        except FileNotFoundError:
            return cache_json_response({"message": "未找到对应城市数据"}, status=404)
        except IndexError:
            return cache_json_response({"message": "未找到对应岗位记录"}, status=404)

        return cache_json_response(detail)

    return blueprint
