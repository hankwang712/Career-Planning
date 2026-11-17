import json

import numpy as np
import pytest

from services.skills.aligner import LLMSkillChooser, SkillAligner, canonical_skills
from services.skills.extraction import SkillExtractor
from services.skills.taxonomy import Skill, SkillTaxonomy, load_taxonomy
from services.skills.embeddings import CachedEmbeddings, embedding_runtime
from services.resume.matcher import _keyword_overlap, _build_capability_scores, build_matcher_state


def test_version_aliases_and_distinct_languages():
    aligner = SkillAligner()
    matched, missing, _ = _keyword_overlap(["Python3", "K8s", "JavaScript", "沟通协调"], ["Python", "Kubernetes", "Java", "跨部门协作"], aligner)
    assert "Python" in matched and "Kubernetes" in matched
    assert "Java" in missing
    assert "JavaScript" not in matched
    assert "团队协作" in matched


def test_unresolved_terms_are_not_reported_as_missing_skills():
    matched, missing, detail = _keyword_overlap([], ["神秘领域工具XYZ", "岗位福利"], SkillAligner())
    assert matched == missing == []
    assert "神秘领域工具XYZ" in detail["unmatched_job_terms"]


def test_similar_vector_is_only_a_candidate_not_equivalence():
    skill = Skill("java", "Java", "tech")
    table = SkillTaxonomy([skill], "test")
    class Vectors:
        def nearest(self, texts, limit):
            return [[(skill, .99)] for _ in texts]
    aligner = SkillAligner(table, vectors=Vectors())
    assert canonical_skills(["JavaScript"], aligner)[0] == {}
    class Chooser:
        def choose(self, items):
            assert items[0][1] == [skill]
            return {0: None}
    aligner.chooser = Chooser()
    assert canonical_skills(["JavaScript"], aligner)[0] == {}


def test_semantic_synonym_requires_and_records_candidate_choice():
    skill = Skill("collaboration", "跨部门协作", "soft")
    class Vectors:
        def nearest(self, texts, limit):
            return [[(skill, .7)] for _ in texts]
    class Chooser:
        calls = 0
        def choose(self, items):
            self.calls += 1
            return {0: skill}
    chooser = Chooser()
    aligner = SkillAligner(SkillTaxonomy([skill], "test"), vectors=Vectors(), chooser=chooser)
    for _ in range(2):
        assert "collaboration" in canonical_skills(["跨团队协调配合"], aligner)[0]
    assert chooser.calls == 1


def test_llm_cannot_select_outside_candidates():
    chooser = LLMSkillChooser(("url", "key", "model"), call=lambda *args, **kwargs: {
        "choices": [{"index": 0, "skill_id": "invented"}]})
    assert chooser.choose([("开发", [Skill("python", "Python", "tech")])]) == {0: None}


def test_grounded_extraction_rejects_hallucination_negation_and_plans():
    result = {"resume": [
        {"phrase": "Python", "quote": "使用Python写脚本"},
        {"phrase": "Java", "quote": "不会Java"},
        {"phrase": "Redis", "quote": "使用Redis"},
        {"phrase": "Go", "quote": "计划学习Go"}],
        "job": [{"phrase": "Python", "quote": "熟悉Python"},
                {"phrase": "Java", "quote": "不要求Java"}]}
    extractor = SkillExtractor(("url", "key", "model"), call=lambda *args, **kwargs: result)
    extracted = extractor.extract("使用Python写脚本；不会Java；计划学习Go", "熟悉Python；不要求Java")
    assert [row["phrase"] for row in extracted["resume"]] == ["Python"]
    assert [row["phrase"] for row in extracted["job"]] == ["Python"]


def test_no_scores_are_invented_from_experience_counts():
    empty = _build_capability_scores({}, [], [])
    assert all(value is None for value in empty.values())
    first = _build_capability_scores({}, ["Python"], ["Java"])
    many = _build_capability_scores({"experiences": [{}] * 50, "projects": [{}] * 100}, ["Python"], ["Java"])
    assert first == many
    assert first["matching"] == 50 and first["professional"] is None
    assert _build_capability_scores({}, [], ["Java"])["matching"] == 0


def test_extracted_skills_drive_match_state_without_truncation():
    table = load_taxonomy()
    names = [skill.name for skill in list(table.skills.values())[:22]]
    matched, missing, _ = _keyword_overlap(names, names, SkillAligner(table))
    assert len(matched) >= 20 and not missing
    state = build_matcher_state({}, {}, "", "目标岗位", extracted_skills={
        "resume": [{"phrase": "Python3", "quote": "Python3"}],
        "job": [{"phrase": "Python", "quote": "Python"}, {"phrase": "Java", "quote": "Java"}]})
    assert state["profile"]["confidence"] is None
    assert state["profile"]["capability_scores"]["matching"] == 50
    assert state["matcher"]["skill_alignment"]["extraction_status"] == "grounded_llm"


def test_existing_embedding_configuration_is_reused(monkeypatch):
    from services import llm_env
    monkeypatch.setattr(llm_env, "_values", lambda: {
        "EMBEDDING_BINDING_HOST": "http://embed", "EMBEDDING_BINDING_API_KEY": "secret", "EMBEDDING_MODEL": "bge-m3"})
    assert embedding_runtime() == ("http://embed", "secret", "bge-m3")


def test_embedding_cache_reuses_only_same_content_and_namespace(tmp_path):
    class Embedder:
        model, namespace = "test", "provider-a"
        calls = []
        def embed(self, texts):
            self.calls.append(texts)
            return np.asarray([[1., 0.] for text in texts])
    embedder = Embedder()
    cache = CachedEmbeddings(embedder, tmp_path / "vectors.sqlite3")
    cache.embed(["one", "one", "two"])
    cache.embed(["one", "three"])
    assert embedder.calls == [["one", "two"], ["three"]]
    embedder.namespace = "provider-b"
    CachedEmbeddings(embedder, cache.path).embed(["one"])
    assert embedder.calls[-1] == ["one"]
