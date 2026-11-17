"""标准技能表：把各种写法对齐到同一个技能编号。

技能表由 backend/scripts/build_skill_taxonomy.py 从招聘数据的技能标签生成（data/knowledge/skills/taxonomy.json），
再用 seed.py 里人工整理的同义词补全。这里提供三种查找：
  lookup        整条短语对齐（会去掉“熟悉…经验”之类修饰、拆开 “A/B” 组合）
  find_in_text  从一段描述里找出提到的所有技能（岗位职责、项目描述）
  candidates    字面相近的候选，交给向量或大模型做最后判断
"""
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from ..paths import DATA_DIR
from .seed import AMBIGUOUS_IN_TEXT
from .text import char_ngrams, phrase_variants, skill_key, split_composite

TAXONOMY_PATH = DATA_DIR / "knowledge" / "skills" / "taxonomy.json"
_ASCII_WORD = re.compile("[0-9a-z]")


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    category: str
    aliases: tuple = field(default=())
    job_count: int = 0

    def public(self):
        return {"id": self.id, "name": self.name, "category": self.category}


class SkillTaxonomy:
    def __init__(self, skills, version=""):
        self.version = version
        self.skills = {skill.id: skill for skill in skills}
        self._by_key = {}
        for skill in sorted(self.skills.values(), key=lambda item: -item.job_count):
            for alias in (skill.name, *skill.aliases):
                self._by_key.setdefault(skill_key(alias), skill.id)
        self._keys = list(self._by_key)
        self._gram_index = defaultdict(set)
        for position, key in enumerate(self._keys):
            for gram in char_ngrams(key):
                self._gram_index[gram].add(position)
        self._text_pattern = self._compile_text_pattern()

    @classmethod
    def from_dict(cls, payload):
        skills = [Skill(item["id"], item["name"], item.get("category", "professional"), tuple(item.get("aliases") or ()),
                        int(item.get("job_count") or 0)) for item in payload.get("skills") or []]
        return cls(skills, str(payload.get("version") or ""))

    def get(self, skill_id):
        return self.skills.get(skill_id)

    def __len__(self):
        return len(self.skills)

    # ---- 整条短语 -------------------------------------------------------------------------------------
    def _exact(self, text):
        for variant in phrase_variants(text):
            skill_id = self._by_key.get(skill_key(variant))
            if skill_id:
                return self.skills[skill_id]
        return None

    def lookup_all(self, text):
        """整条短语对应的技能；“TensorFlow/PyTorch”这样的组合会返回多项。对不上时返回空列表。"""
        whole = self._exact(text)
        if whole:
            return [whole]
        parts = split_composite(text)
        if len(parts) < 2:
            return []
        found = [self._exact(part) for part in parts]
        unique = []
        for skill in found:
            if skill and skill not in unique:
                unique.append(skill)
        return unique

    def lookup(self, text):
        found = self.lookup_all(text)
        return found[0] if len(found) == 1 else None

    # ---- 长文本扫描 -------------------------------------------------------------------------------------
    def _compile_text_pattern(self):
        aliases = {}
        for skill in self.skills.values():
            if skill.category == "domain":
                continue  # 行业词在岗位描述里到处出现，扫描它们只会制造噪声
            for alias in (skill.name, *skill.aliases):
                text = unicodedata.normalize("NFKC", alias).casefold().strip()
                key = skill_key(text)
                if len(key) < 2 or key in AMBIGUOUS_IN_TEXT:
                    continue
                aliases.setdefault(text, skill.id)
        if not aliases:
            return None
        parts = []
        for alias in sorted(aliases, key=len, reverse=True):
            escaped = re.escape(alias)
            # 英文技能要求完整单词，避免 “java” 命中 “javascript”、“sql” 命中 “mysql”
            if _ASCII_WORD.search(alias[0]):
                escaped = "(?<![0-9a-z+#.])" + escaped
            if _ASCII_WORD.search(alias[-1]) or alias[-1] in "+#":
                escaped += "(?![0-9a-z+#])"
            parts.append(escaped)
        self._text_aliases = aliases
        return re.compile("|".join(parts))

    def find_in_text(self, text, limit=None):
        """描述里提到的技能，按首次出现的位置排序、去重。"""
        if not self._text_pattern or not text:
            return []
        normalized = unicodedata.normalize("NFKC", str(text)).casefold()
        found, seen = [], set()
        for match in self._text_pattern.finditer(normalized):
            skill_id = self._text_aliases.get(match.group(0))
            if skill_id and skill_id not in seen:
                seen.add(skill_id)
                found.append(self.skills[skill_id])
                if limit and len(found) >= limit:
                    break
        return found

    # ---- 候选召回 -------------------------------------------------------------------------------------
    def candidates(self, text, limit=8):
        """字面相近的候选技能及相似度（Dice 系数，0~1），用于整条对不上时的下一步判断。"""
        scores = {}
        for variant in phrase_variants(text):
            key = skill_key(variant)
            grams = char_ngrams(key)
            if not grams:
                continue
            overlap = defaultdict(int)
            for gram in grams:
                for position in self._gram_index.get(gram, ()):
                    overlap[position] += 1
            for position, shared in overlap.items():
                other = char_ngrams(self._keys[position])
                score = 2 * shared / (len(grams) + len(other))
                skill_id = self._by_key[self._keys[position]]
                if score > scores.get(skill_id, 0):
                    scores[skill_id] = score
        ranked = sorted(scores.items(), key=lambda item: (-item[1], -self.skills[item[0]].job_count))
        return [(self.skills[skill_id], round(score, 4)) for skill_id, score in ranked[:limit]]


@lru_cache(maxsize=1)
def _load_cached(path_text, modified):
    with open(path_text, encoding="utf-8") as handle:
        return SkillTaxonomy.from_dict(json.load(handle))


def load_taxonomy(path=TAXONOMY_PATH):
    """读取技能表；文件更新后自动重新加载。文件不存在时返回空表（各处退回原样比较）。"""
    try:
        return _load_cached(str(path), path.stat().st_mtime_ns)
    except FileNotFoundError:
        return SkillTaxonomy([])
