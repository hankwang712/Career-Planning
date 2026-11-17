"""从招聘数据的技能标签生成标准技能表。

做法：
  1. 统计标签出现次数，丢掉工作形式、福利、学历这类非技能标签（seed.NOISE_PATTERNS）；
  2. 先放入人工整理的同义词组（seed.ALIAS_GROUPS），再按出现次数从高到低处理“干净”的标签，
     规整键相同的写法（Python / python）并成一组；
  3. 再处理带修饰或组合的标签：“机器学习经验”去掉后缀能对上“机器学习”就作为它的别名，
     “TensorFlow/PyTorch”拆开后分别计入；对不上的保留为独立技能；
  4. 出现次数太少的组丢弃（人工种子始终保留）。
"""
import hashlib
import json
import re
from collections import Counter

from .seed import ALIAS_GROUPS, DOMAIN_TERMS, NOISE_PATTERNS
from .text import phrase_variants, skill_key, split_composite

_NOISE = re.compile("|".join(NOISE_PATTERNS))
_HAS_ASCII = re.compile("[A-Za-z]")
DOMAIN_KEYS = {skill_key(term) for term in DOMAIN_TERMS}


def is_noise(tag):
    text = str(tag or "").strip()
    return not text or len(text) > 24 or bool(_NOISE.search(text))


def _decorated(tag):
    return len(phrase_variants(tag)) > 1 or len(split_composite(tag)) > 1


def build_taxonomy(tag_counts, industry_names=(), min_count=3):
    industry_keys = {skill_key(name) for name in industry_names}
    groups = {}       # id -> {"name", "category", "aliases": Counter, "count", "seed"}
    alias_owner = {}  # key -> id

    def add_group(name, category, seed=False):
        skill_id = skill_key(name)
        groups[skill_id] = {"name": name, "category": category, "aliases": Counter(), "count": 0, "seed": seed}
        alias_owner.setdefault(skill_id, skill_id)
        return skill_id

    def attach(skill_id, alias, count):
        groups[skill_id]["aliases"][alias] += count
        groups[skill_id]["count"] += count
        alias_owner.setdefault(skill_key(alias), skill_id)

    def resolve(tag):
        for variant in phrase_variants(tag):
            owner = alias_owner.get(skill_key(variant))
            if owner:
                return owner
        return None

    for category, names in ALIAS_GROUPS:
        skill_id = add_group(names[0], category, seed=True)
        for alias in names[1:]:
            groups[skill_id]["aliases"][alias] += 0
            alias_owner.setdefault(skill_key(alias), skill_id)

    cleaned = Counter()
    for tag, count in tag_counts.items():
        text = str(tag or "").strip()
        if not is_noise(text):
            cleaned[text] += count

    plain = sorted((tag for tag in cleaned if not _decorated(tag)), key=lambda tag: -cleaned[tag])
    decorated = sorted((tag for tag in cleaned if _decorated(tag)), key=lambda tag: -cleaned[tag])

    for tag in plain:
        owner = alias_owner.get(skill_key(tag))
        if owner is None:
            owner = add_group(tag, "professional")
        attach(owner, tag, cleaned[tag])

    for tag in decorated:
        owner = resolve(tag)
        if owner:
            attach(owner, tag, cleaned[tag])
            continue
        parts = split_composite(tag)
        owners = [resolve(part) for part in parts] if len(parts) > 1 else []
        if owners and all(owners):
            for part_owner in dict.fromkeys(owners):
                groups[part_owner]["count"] += cleaned[tag]
            continue
        attach(add_group(tag, "professional"), tag, cleaned[tag])

    skills = []
    for skill_id, group in groups.items():
        if not group["seed"] and group["count"] < min_count:
            continue
        # 展示名称用最常见的写法，人工种子保留规定的写法
        # 展示名称优先用不带“经验/能力”修饰的写法
        plain_aliases = [(alias, count) for alias, count in group["aliases"].most_common() if not _decorated(alias)]
        if group["seed"] or not group["aliases"]:
            name = group["name"]
        else:
            name = (plain_aliases or group["aliases"].most_common())[0][0]
        category = group["category"]
        if category == "professional":
            if skill_id in industry_keys or skill_id in DOMAIN_KEYS:
                category = "domain"
            elif name.endswith("产品"):
                category = "product"
            elif _HAS_ASCII.search(name):
                category = "tech"
        aliases = sorted({alias for alias in group["aliases"] if alias != name}, key=lambda alias: (-group["aliases"][alias], alias))
        skills.append({"id": skill_id, "name": name, "category": category, "aliases": aliases, "job_count": group["count"]})
    skills.sort(key=lambda item: (-item["job_count"], item["id"]))
    body = json.dumps(skills, ensure_ascii=False, sort_keys=True)
    return {"version": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16], "skill_count": len(skills), "skills": skills}
