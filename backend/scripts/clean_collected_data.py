import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EMPTY_VALUES = {"", "null", "none", "nan", "n/a", "暂无", "未知", "未提供", "--", "-"}
IGNORED_PUNCTUATION = re.compile(r"[\s，,。;；:：、!?！？（）()\[\]【】“”‘’\"'·•…]+")


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden_depth = 0

    def handle_starttag(self, tag, attributes):
        if tag in {"script", "style"}:
            self.hidden_depth += 1
        elif tag in {"p", "br", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        elif tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, text):
        if not self.hidden_depth:
            self.parts.append(text)


def clean_text(value):
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(str(value)))
    if re.search(r"</?(?:p|br|div|span|li|ul|ol|script|style|strong|a)(?:\s|>|/)", text, re.I):
        extractor = TextExtractor()
        extractor.feed(text)
        text = "".join(extractor.parts)
    text = "".join(character for character in text if not unicodedata.category(character).startswith("C") or character in "\n\r\t")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return "" if text.casefold() in EMPTY_VALUES else text


def compact(value):
    return re.sub(r"\s+", "", clean_text(value).casefold())


def content_key(value):
    return IGNORED_PUNCTUATION.sub("", clean_text(value).casefold())


def unique_text(values):
    results = {}
    for value in values:
        text = clean_text(value)
        if text:
            results.setdefault(compact(text), text)
    return list(results.values())


def skills_list(value):
    if isinstance(value, str):
        value = re.split(r"[,，;；、\n|]+", value)
    return unique_text(value or [])


def locations_list(value):
    if not isinstance(value, list):
        value = [value]
    locations = []
    for location in value:
        if isinstance(location, dict):
            location = location.get("name") or location.get("city") or location.get("display")
        text = clean_text(location)
        if text:
            locations.append(text.removesuffix("市"))
    return sorted(unique_text(locations), key=compact)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def local_ref(path, dataset, position, record_id="", **extra):
    return {"dataset": dataset, "file": path.relative_to(ROOT).as_posix(), "row": position, "record_id": str(record_id), **extra}


def normalize_job(raw, reference, default_city=""):
    if reference["dataset"] == "job_research_hub":
        source = raw.get("source") or {}
        reference.update({key: source.get(key) or "" for key in ("platform", "url", "collected_at")})
        salary = raw.get("salary") or {}
        education = raw.get("education") or {}
        return {
            "company": clean_text(raw.get("company_name")), "title": clean_text(raw.get("title")),
            "locations": locations_list(raw.get("locations") or []),
            "salary": clean_text(salary.get("display") if isinstance(salary, dict) else salary),
            "education": clean_text(education.get("display") if isinstance(education, dict) else education),
            "experience": clean_text(raw.get("experience")),
            "recruitment_type": clean_text(raw.get("recruitment_type")),
            "graduation_year": clean_text(raw.get("graduation_year")),
            "skills": skills_list(raw.get("skills")), "description": clean_text(raw.get("full_jd")),
            "responsibilities": clean_text(raw.get("responsibilities")), "requirements": clean_text(raw.get("requirements")),
            "published_at": clean_text(raw.get("published_at")), "updated_at": clean_text(raw.get("updated_at")),
            "industry": clean_text(raw.get("company_industry")), "company_scale": clean_text(raw.get("company_scale")),
            "company_description": "", "work_address": "", "sources": [reference],
        }
    address = clean_text(raw.get("工作地址") or raw.get("地址"))
    city = raw.get("城市") or raw.get("采集城市") or default_city
    if not city:
        city = re.split(r"[_-]", address)[0]
    return {
        "company": clean_text(raw.get("公司名称")), "title": clean_text(raw.get("岗位名称")),
        "locations": locations_list(city), "salary": clean_text(raw.get("薪资") or raw.get("薪资范围")),
        "education": clean_text(raw.get("学历要求")), "experience": clean_text(raw.get("经验要求")),
        "recruitment_type": "", "graduation_year": "", "skills": skills_list(raw.get("技能要求")),
        "description": clean_text(raw.get("岗位描述") or raw.get("岗位详情")),
        "responsibilities": "", "requirements": "", "published_at": "", "updated_at": clean_text(raw.get("更新日期")),
        "industry": clean_text(raw.get("公司行业") or raw.get("所属行业")), "company_scale": clean_text(raw.get("公司规模")),
        "company_description": clean_text(raw.get("公司简介") or raw.get("公司详情")),
        "work_address": address, "sources": [reference],
    }


def iter_jobs():
    for path in sorted((ROOT / "data/jobs").glob("*.json")):
        for position, raw in enumerate(read_json(path), 1):
            yield normalize_job(raw, local_ref(path, "city_jobs", position, raw.get("采集序号", position)), path.stem)
    path = ROOT / "data/raw/other_city.json"
    for position, raw in enumerate(read_json(path), 1):
        yield normalize_job(raw, local_ref(path, "other_city", position, raw.get("岗位编码", position)))
    directory = ROOT / "data/raw/recruitment/job_research_hub"
    manifest = read_json(directory / "manifest.json")
    for shard in manifest["shards"]:
        path = directory / shard["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != shard["sha256"]:
            raise ValueError(f"Source checksum mismatch: {path}")
        with gzip.open(path, "rt", encoding="utf-8-sig") as stream:
            for position, line in enumerate(stream, 1):
                raw = json.loads(line)
                yield normalize_job(raw, local_ref(path, "job_research_hub", position, raw.get("record_id", "")))


def compatible(left, right):
    for field in ("salary", "education", "experience", "recruitment_type", "graduation_year", "work_address"):
        if left.get(field) and right.get(field) and compact(left[field]) != compact(right[field]):
            return False
    left_year = re.match(r"\d{4}", left.get("published_at", ""))
    right_year = re.match(r"\d{4}", right.get("published_at", ""))
    return not (left_year and right_year and left_year.group() != right_year.group())


def merge_jobs(records):
    buckets = defaultdict(list)
    kept = []
    rejected = []
    counts = Counter()
    inputs = Counter()
    duplicates_by_source = Counter()
    rejected_by_source = Counter()
    for record in records:
        dataset = record["sources"][0]["dataset"]
        inputs[dataset] += 1
        missing = [field for field in ("company", "title", "description") if not record[field]]
        if missing:
            counts["rejected"] += 1
            rejected_by_source[dataset] += 1
            rejected.append({"reason": "missing_" + "_and_".join(missing), "sources": record["sources"]})
            continue
        key = (compact(record["company"]), compact(record["title"]), tuple(map(compact, record["locations"])), content_key(record["description"]))
        match = next((candidate for candidate in buckets[key] if compatible(candidate, record)), None)
        if match is None:
            buckets[key].append(record)
            kept.append(record)
            continue
        counts["exact_duplicates" if match["description"] == record["description"] else "formatting_duplicates"] += 1
        duplicates_by_source[dataset] += 1
        counts["cross_source_merges"] += record["sources"][0]["dataset"] not in {source["dataset"] for source in match["sources"]}
        match["sources"].extend(record["sources"])
        match["skills"] = unique_text(match["skills"] + record["skills"])
        for field, value in record.items():
            if field not in {"sources", "skills"} and not match.get(field) and value:
                match[field] = value
    for record in kept:
        seed = json.dumps({key: value for key, value in record.items() if key != "sources"}, sort_keys=True, ensure_ascii=False)
        record["id"] = "job_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
        flags = []
        if not record["locations"]:
            flags.append("missing_location")
        if not record["salary"]:
            flags.append("missing_salary")
        if not any(re.match(r"^https?://[^/\s]+", source.get("url", "")) for source in record["sources"]):
            flags.append("missing_source_url")
        record["quality_flags"] = flags
    return kept, rejected, {
        "input_by_source": dict(inputs), "input_records": sum(inputs.values()), "output_records": len(kept),
        "duplicates_by_source": dict(duplicates_by_source), "rejected_by_source": dict(rejected_by_source),
        "output_by_source": dict(Counter(record["sources"][0]["dataset"] for record in kept)), **dict(counts),
    }


def clean_knowledge():
    concepts = {}
    input_counts = Counter()

    def add(name, kind, scope, description, source):
        name = clean_text(name)
        input_counts[source["dataset"]] += 1
        key = (kind, compact(name), scope)
        if key not in concepts:
            concepts[key] = {"id": "concept_" + hashlib.sha256(json.dumps(key, ensure_ascii=False).encode()).hexdigest()[:24],
                             "kind": kind, "name": name, "description": clean_text(description), "sources": []}
        concepts[key]["sources"].append(source)

    path = ROOT / "data/knowledge/china_occupations_2022/occupations_community.json"
    data = read_json(path)
    for occupation in data["occupations"]:
        parent = data["minor_categories"].get(occupation["minor"], "")
        scope = parent if occupation["name"].startswith("其他") else ""
        add(occupation["name"], "occupation", scope, "", {
            "dataset": "china_occupations_2022", "file": path.relative_to(ROOT).as_posix(),
            "code": occupation["code"], "parent_code": occupation["minor"], "parent_name": parent,
        })
    path = ROOT / "data/knowledge/chinese_occupations/occupations.json"
    common = read_json(path)
    parents = {category["code"]: category["name"] for category in common["000000"]}
    for parent_code, occupations in common.items():
        if parent_code == "000000":
            continue
        for occupation in occupations:
            parent = parents[parent_code]
            scope = parent if occupation["name"].startswith("其他") else ""
            add(occupation["name"], "occupation", scope, "", {
                "dataset": "common_chinese_occupations", "file": path.relative_to(ROOT).as_posix(),
                "code": occupation["code"], "parent_code": parent_code, "parent_name": parent,
            })
    path = ROOT / "data/knowledge/china_industries/industries.json"

    def add_industries(nodes, parent_code="", level=1):
        for code, industry in nodes.items():
            add(industry["name"], "industry", code, industry.get("description"), {
                "dataset": "china_industries_2017", "file": path.relative_to(ROOT).as_posix(),
                "code": code, "parent_code": parent_code, "level": level,
            })
            add_industries(industry.get("children") or {}, code, level + 1)

    add_industries(read_json(path))
    records = list(concepts.values())
    return records, {"input_by_source": dict(input_counts), "input_records": sum(input_counts.values()),
                     "output_records": len(records), "merged_equivalent_names": sum(input_counts.values()) - len(records),
                     "output_by_kind": dict(Counter(record["kind"] for record in records))}


def write_jsonl(path, records):
    if path.suffix == ".gz":
        stream = gzip.open(path, "wt", encoding="utf-8", compresslevel=6)
    else:
        stream = path.open("w", encoding="utf-8")
    with stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/cleaned/merged")
    arguments = parser.parse_args()
    output = arguments.output_dir.resolve()
    source_paths = list((ROOT / "data/jobs").glob("*.json")) + [ROOT / "data/raw/other_city.json"]
    source_paths += list((ROOT / "data/raw/recruitment/job_research_hub").glob("jobs-*.jsonl.gz"))
    source_paths += [ROOT / "data/knowledge/china_occupations_2022/occupations_community.json",
                     ROOT / "data/knowledge/chinese_occupations/occupations.json", ROOT / "data/knowledge/china_industries/industries.json"]
    input_hashes = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    records, rejected, job_summary = merge_jobs(iter_jobs())
    knowledge, knowledge_summary = clean_knowledge()
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "jobs.jsonl.gz", records)
    write_jsonl(output / "knowledge.jsonl", knowledge)
    write_jsonl(output / "rejected_jobs.jsonl", rejected)
    summary = {
        "schema_version": 1, "jobs": job_summary, "knowledge": knowledge_summary,
        "rejection_reasons": dict(Counter(record["reason"] for record in rejected)),
        "job_quality_flags": dict(Counter(flag for record in records for flag in record["quality_flags"])),
        "skipped_derived_sources": [{"path": "data/cleaned/other_city_boss_format.json",
                                     "records": len(read_json(ROOT / "data/cleaned/other_city_boss_format.json")),
                                     "reason": "Derived from data/raw/other_city.json; raw input is included instead."}],
        "input_sha256": input_hashes,
        "policy": "Merge only matching company, title, location and full JD after whitespace/punctuation normalization. Keep conflicting salary, education, experience, recruitment cohort, work address or publication year separate. Retain all source references. Industry codes and occupation types are never merged together.",
        "source_catalogs": ["data/knowledge/catalog.json", "data/raw/recruitment/catalog.json"],
        "application_integration": "On-demand dataset browser; original city analytics sources are unchanged.",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.path.insert(0, str(ROOT / "backend"))
    from services.datasets import build_index
    build_index(output)
    print(json.dumps({"jobs": job_summary, "knowledge": knowledge_summary, "rejection_reasons": summary["rejection_reasons"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
