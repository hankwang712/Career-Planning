"""从清洗后的招聘数据生成标准技能表：python backend/scripts/build_skill_taxonomy.py

输出 data/knowledge/skills/taxonomy.json（随仓库提交）。同义词与过滤规则在 backend/services/skills/seed.py。
"""
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.paths import DATA_DIR  # noqa: E402
from services.skills.build import build_taxonomy  # noqa: E402
from services.skills.taxonomy import TAXONOMY_PATH  # noqa: E402


def main():
    merged = DATA_DIR / "cleaned" / "merged"
    tags = Counter()
    with gzip.open(merged / "jobs.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            for tag in json.loads(line).get("skills") or []:
                tags[str(tag).strip()] += 1
    industries = set()
    with open(merged / "knowledge.jsonl", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("kind") == "industry":
                industries.add(record["name"])
    taxonomy = build_taxonomy(tags, industries)
    TAXONOMY_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAXONOMY_PATH.write_text(json.dumps(taxonomy, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{taxonomy['skill_count']} 个技能，版本 {taxonomy['version']} → {TAXONOMY_PATH}")


if __name__ == "__main__":
    main()
