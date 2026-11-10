import tempfile
import unittest
from pathlib import Path

from backend.advisor.agents.job import JobAnalysisAgent, verify_job_evidence
from backend.advisor.schemas.job import JobAnalysisInput
from backend.advisor.tools.job_retrieval import local_job_candidates
from backend.advisor.utils.job_grounding import requirement_source_ids, verify_job_grounding, source_location_conflicts, preferred_condition_promoted


def analysis(relevance="direct", requirement="required", quote="具备Python开发能力", category="skill"):
    return {"summary": "仅分析本次来源。", "findings": [{"category": category,
        "statement": "具备Python开发能力", "requirement": requirement,
        "evidence": [{"chunk_id": "JD1", "quote": quote}]}], "related_roles": [], "limitations": [],
        "source_assessments": [{"chunk_id": "JD1", "relevance": relevance,
            "reason": "职责属于目标方向。", "quote": "开发知识库问答应用"}]}


SOURCES = [{"chunk_id": "JD1", "content": "岗位职责：开发知识库问答应用。任职要求：具备Python开发能力；有LangGraph经验者优先。"}]


class JobGroundingTests(unittest.TestCase):
    def test_location_conflicts_preserve_both_header_and_body(self):
        sources = [{"chunk_id": "JD1", "content": "城市：上海\n岗位描述：\n实习地点:杭州\n负责应用开发。"}]
        conflict = source_location_conflicts(sources)
        self.assertEqual(conflict[0]["metadata_city"], "上海")
        self.assertEqual(conflict[0]["body_location"], "杭州")
        self.assertEqual(source_location_conflicts([{**sources[0], "content": sources[0]["content"].replace("城市：上海", "城市：杭州市")}]), [])

    def test_adjacent_source_cannot_provide_core_requirement(self):
        self.assertTrue(verify_job_grounding(analysis(relevance="adjacent"), SOURCES))
        self.assertTrue(verify_job_grounding(analysis(relevance="unrelated"), SOURCES))

    def test_exclusion_is_not_a_required_gate(self):
        result = analysis(category="other")
        self.assertTrue(verify_job_grounding(result, SOURCES))
        result["findings"][0]["requirement"] = "unspecified"
        result["source_assessments"][0]["relevance"] = "unrelated"
        self.assertEqual(verify_job_grounding(result, SOURCES), [])
        self.assertEqual(requirement_source_ids(result), [])

    def test_required_and_preferred_cannot_mix(self):
        result = analysis(quote="有LangGraph经验者优先")
        self.assertTrue(verify_job_grounding(result, SOURCES))
        result["findings"][0]["requirement"] = "preferred"
        self.assertEqual(verify_job_grounding(result, SOURCES), [])

    def test_adjacent_preference_does_not_invalidate_separate_required_claim(self):
        self.assertFalse(preferred_condition_promoted("要求本科或研究生在读", ["211及以上院校在读,本科或研究生,研究生优先"]))
        self.assertFalse(preferred_condition_promoted("要求2027届本科及以上学历在读", ["2027届本科及以上学历在读,计算机、人工智能等相关专业优先"]))
        self.assertTrue(preferred_condition_promoted("要求掌握LangGraph", ["熟悉Python；有LangGraph经验者优先"]))

    def test_complete_relevance_inventory_and_citations_are_required(self):
        result = analysis()
        self.assertEqual(verify_job_evidence(result, SOURCES, require_assessments=True), [])
        self.assertEqual(requirement_source_ids(result), ["JD1"])
        result["source_assessments"][0]["quote"] = "杜撰VLM模型预训练职责"
        self.assertTrue(verify_job_evidence(result, SOURCES, require_assessments=True))
        result["source_assessments"] = []
        self.assertTrue(verify_job_grounding(result, SOURCES))

    def test_model_schema_feedback_rejects_unrelated_core_claim(self):
        agent = JobAnalysisAgent(None)
        schema = agent.get_output_schema({"retrieval": {"sources": SOURCES}})
        with self.assertRaises(ValueError):
            schema.model_validate(analysis(relevance="unrelated"))
        self.assertEqual(schema.model_validate(analysis()).findings[0].requirement, "required")

    def test_literal_mixed_education_condition_is_split_without_new_facts(self):
        sources = [{"chunk_id": "JD1", "content": "开发知识库问答应用。211及以上院校在读,本科或研究生,研究生优先"}]
        data = analysis(quote="211及以上院校在读,本科或研究生,研究生优先", category="education")
        data["findings"][0]["statement"] = "211及以上院校在读，本科或研究生，研究生优先"
        schema = JobAnalysisAgent(None).get_output_schema({"retrieval": {"sources": sources}})
        result = schema.model_validate(data)
        self.assertEqual([item.requirement for item in result.findings], ["required", "preferred"])
        self.assertIn("在读", result.findings[0].statement)
        self.assertEqual(result.findings[1].statement, "研究生优先")

    def test_local_recall_preserves_whole_record_and_actual_source(self):
        separator = "=" * 80
        def record(title, body):
            return f"岗位名称：{title}\n企业：示例科技\n城市：杭州\n学历：本科\n\n岗位描述：\n{body}"
        content = (record("普通后端工程师", "只做企业接口。") + "\n\n" + separator + "\n\n"
                   + record("多模态算法工程师", "研究视觉语言模型。\n" + separator + "\n正文中的分隔线后仍是同一岗位。"))
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "jobs.txt"
            path.write_text(content, encoding="utf-8")
            with patch.dict("os.environ", {"JOB_JD_SOURCE_PATH": str(path)}):
                rows = local_job_candidates(JobAnalysisInput(target_role="多模态算法工程师"))
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0]["file_path"].endswith("#record=2"))
            self.assertIn("正文中的分隔线后仍是同一岗位", rows[0]["content"])
            self.assertEqual(rows[0]["reference_id"], "local_export")

    def test_acronym_capitalization_is_restored_from_source(self):
        from backend.advisor.utils.evidence import copy_source_quote
        self.assertEqual(copy_source_quote("熟悉MCP/Skill", "要求熟悉MCP/SKill，有实践。"), "熟悉MCP/SKill")
        self.assertIsNone(copy_source_quote("熟悉MCP和Skill", "要求熟悉MCP/SKill，有实践。"))

    def test_negated_preference_does_not_change_literal_requirement(self):
        data = analysis()
        data['findings'][0]['statement'] = '属于硬性要求而非优先条件'
        self.assertEqual(verify_job_evidence(data, SOURCES, require_assessments=True), [])


if __name__ == "__main__":
    unittest.main()
