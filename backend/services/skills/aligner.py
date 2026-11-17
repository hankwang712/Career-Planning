"""把任意写法的技能对齐到标准技能表。

两阶段做法（先召回候选、再判断是否同义）：
  1. 整条对齐：规整写法、去掉“熟悉…经验”修饰、拆开 “A/B”，命中别名就直接确定；
  2. 召回候选：字面相近（字符 n-gram）＋语义相近（向量，可选）；
  3. 判断：非明确别名必须交给大模型从候选里选出“含义相同”的一项，或判定都不是。
长句（岗位职责、项目描述）不做整条对齐，而是从中找出提到的所有标准技能。

没有配置向量和大模型时只走第 1、2 步的字面部分，结果仍然稳定、可复现。
"""
import json
import logging
import threading
from dataclasses import dataclass

from .taxonomy import Skill, load_taxonomy
from .text import skill_key
from .extraction import negated

logger = logging.getLogger(__name__)

REVIEW_FLOOR = 0.45     # 低于这个值连候选都不算，直接判为标准表里没有
LONG_TEXT = 30          # 超过这个长度、或带句读的，按描述扫描而不是整条对齐


@dataclass(frozen=True)
class AlignedSkill:
    raw: str
    skill: Skill | None
    method: str          # exact / text / lexical / vector / llm / unmatched
    score: float = 1.0

    def public(self):
        return {"raw": self.raw, "method": self.method, "score": self.score,
                **({"skill": self.skill.public()} if self.skill else {"skill": None})}


def _is_description(text):
    return len(text) > LONG_TEXT or any(mark in text for mark in "。；;！!？?\n")


class LLMSkillChooser:
    """让大模型从候选里挑“同一技能”。只能选候选里的编号或判为没有，选不在候选里的编号会被丢弃。"""

    SYSTEM = (
        "你是技能标准化助手。对每个技能短语，从它的候选标准技能里选出含义相同的一项。"
        "只有指同一项技能（同义词、缩写、不同写法）才算相同；上位概念、下位概念、只是相关的都不算，此时返回 null。"
        "只输出 JSON：{\"choices\": [{\"index\": 序号, \"skill_id\": \"候选编号或 null\"}]}。"
    )

    def __init__(self, runtime, call=None):
        from ..llm_calls import call_structured_chat

        self.runtime = runtime
        self._call = call or call_structured_chat

    def choose(self, items):
        """items: [(短语, [Skill...])] → {序号: Skill 或 None}"""
        if not items:
            return {}
        payload = [{"index": index, "phrase": phrase,
                    "candidates": [{"skill_id": skill.id, "name": skill.name, "aliases": list(skill.aliases[:8])} for skill in candidates]}
                   for index, (phrase, candidates) in enumerate(items)]
        base_url, api_key, model = self.runtime
        result = self._call(base_url, api_key, model,
                            [{"role": "user", "content": json.dumps({"items": payload}, ensure_ascii=False)}],
                            self.SYSTEM, max_tokens=min(6000, 2048 + 64 * len(items)))
        allowed = {index: {skill.id: skill for skill in candidates} for index, (_, candidates) in enumerate(items)}
        chosen = {}
        for row in (result or {}).get("choices") or []:
            try:
                index = int(row.get("index"))
            except (TypeError, ValueError):
                continue
            skill_id = row.get("skill_id")
            if index in allowed:
                chosen[index] = allowed[index].get(skill_id) if isinstance(skill_id, str) else None
        return chosen


class SkillAligner:
    def __init__(self, taxonomy=None, *, vectors=None, chooser=None):
        self.taxonomy = taxonomy if taxonomy is not None else load_taxonomy()
        self.vectors = vectors
        self.chooser = chooser
        self._decisions = {}   # 大模型的判断按（技能表版本，规整后的短语）缓存，同一写法只问一次
        self._lock = threading.Lock()

    def align(self, items):
        """对齐一组短语，返回 AlignedSkill 列表（长句可能展开成多项，对不上的标为 unmatched）。"""
        results, pending = [], []
        for raw in items or []:
            text = str(raw or "").strip()
            if not text:
                continue
            if _is_description(text):
                results.extend(AlignedSkill(text, skill, "text") for skill in self.taxonomy.find_in_text(text)
                               if not any(negated(text, alias) for alias in (skill.name, *skill.aliases) if alias in text))
                continue
            if negated(text, text):
                continue
            exact = self.taxonomy.lookup_all(text)
            if exact:
                results.extend(AlignedSkill(text, skill, "exact") for skill in exact)
                continue
            slot = len(results)
            results.append(AlignedSkill(text, None, "unmatched", 0.0))
            pending.append((slot, text))
        if pending:
            self._resolve(results, pending)
        return results

    def _resolve(self, results, pending):
        texts = [text for _, text in pending]
        lexical = [self.taxonomy.candidates(text, 6) for text in texts]
        semantic = [[] for _ in texts]
        if self.vectors is not None:
            try:
                semantic = self.vectors.nearest(texts, 6)
            except Exception as exc:  # 向量服务不可用时退回字面方法
                logger.warning("技能向量检索失败，改用字面匹配：%s", type(exc).__name__)
        review = []
        for (slot, text), lex, sem in zip(pending, lexical, semantic):
            cached = self._decisions.get((self.taxonomy.version, skill_key(text)))
            if cached is not None:
                skill, score = cached
                results[slot] = AlignedSkill(text, skill, "llm" if skill else "unmatched", score)
                continue
            # Similarity recalls candidates; it cannot establish skill equivalence.
            merged = {}
            for skill, score in [*lex, *sem]:
                if skill and score >= REVIEW_FLOOR and score > merged.get(skill.id, (None, 0))[1]:
                    merged[skill.id] = (skill, score)
            candidates = sorted(merged.values(), key=lambda item: -item[1])[:6]
            if candidates:
                review.append((slot, text, candidates))
        if not review or self.chooser is None:
            return
        try:
            chosen = self.chooser.choose([(text, [skill for skill, _ in candidates]) for _, text, candidates in review])
        except Exception as exc:
            logger.warning("技能对齐的大模型判断失败，保留字面结果：%s", type(exc).__name__)
            return
        for index, (slot, text, candidates) in enumerate(review):
            if index not in chosen:
                continue
            skill = chosen[index]
            score = next((value for candidate, value in candidates if skill and candidate.id == skill.id), 0.0)
            with self._lock:
                self._decisions[(self.taxonomy.version, skill_key(text))] = (skill, score)
            results[slot] = AlignedSkill(text, skill, "llm" if skill else "unmatched", score)


def build_default_aligner():
    """按 .env 配置组装：有向量模型就加语义候选，有对话模型就加大模型判断。"""
    from .. import llm_env
    from .embeddings import TaxonomyVectors, default_embedder

    taxonomy = load_taxonomy()
    embedder = default_embedder()
    vectors = TaxonomyVectors(taxonomy, embedder) if embedder else None
    chooser = LLMSkillChooser(llm_env.chat_runtime()) if llm_env.chat_configured() else None
    return SkillAligner(taxonomy, vectors=vectors, chooser=chooser)


_default = {"aligner": None, "version": None}


def default_aligner():
    from ..llm_env import chat_runtime
    from .embeddings import embedding_runtime
    taxonomy = load_taxonomy()
    import hashlib
    version = hashlib.sha256(repr((taxonomy.version, chat_runtime(), embedding_runtime())).encode()).hexdigest()
    if _default["aligner"] is None or _default["version"] != version:
        _default["aligner"] = build_default_aligner()
        _default["version"] = version
    return _default["aligner"]


def canonical_skills(items, aligner=None):
    """对齐后的结果整理成：{技能编号: (Skill, [原始写法...])}，以及对不上的原始短语。"""
    aligned = (aligner or default_aligner()).align(items)
    matched, unmatched = {}, []
    for item in aligned:
        if item.skill is None:
            unmatched.append(item.raw)
            continue
        entry = matched.setdefault(item.skill.id, (item.skill, []))
        if item.raw not in entry[1]:
            entry[1].append(item.raw)
    return matched, unmatched
