"""Regression cases derived from reader-facing report quality failures; no personal data or network."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.services.report.presentation import ReportPresentation, SCOPE_NOTE, reader_limitations, validate_reader_report
from backend.services.report.workflow_report import build_report_bundle
from backend.services.report.reader_sections import priority_checks
from backend.scripts.check_report_workflow import RESUME, job_result, decision_result, action_result
from backend.scripts.check_report_planning import ScriptedModel
from backend.services.report.planning import ReportActionPlanningAgent
from experiments.news_advisor.agents.career_decision import CareerDecisionAgent
from experiments.news_advisor.agents.resume import ResumeAnalysisAgent
from experiments.news_advisor.utils.dates import education_timeline_context, verify_education_timeline_claims


EDUCATION = "本科 2023.09-2027.06；研究生计划 2027.09入学"
FALSE_OVERLAP = "简历中2027.09入学与本科2023.09-2027.06的时间表述存在重叠。"


def fixture():
    job = job_result()
    chunk = "chunk-" + "a" * 32
    job["sources"][0].update(chunk_id=chunk, file_path="C:/private/jobs.txt#record=110",
        content="招聘记录内部键：jd-internal\n岗位名称：智能体开发实习生 企业：示例企业 城市：上海 学历：本科\n" + job["sources"][0]["content"])
    job["data"]["findings"][0]["evidence"][0]["chunk_id"] = chunk
    inputs = {"raw_resume": RESUME + "\n" + EDUCATION,
              "targets": [{"target_id": "T1", "title": "智能体开发", "job_analysis": job}]}
    decision = decision_result(inputs)
    decision["data"]["summary"] = "方向 T1 值得尝试，JD1 的 Python 要求有项目支持。"
    decision["data"]["limitations"] += ["仅依据岗位样本，不代表整个方向或招聘市场。", "保留接口返回的 chunk，JD 数按 record 来源去重。"]
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    constraints = {"start_date": today.isoformat(), "deadline": (today + timedelta(days=13)).isoformat(),
                   "weekly_hours": 8, "budget": 0, "student_stage": "employment"}
    planning_input = {"decision_input": inputs, "decision_result": decision, "target_id": "T1", "constraints": constraints}
    plan = action_result(planning_input)
    plan["data"]["summary"] = "assessment.decision=conditional；先完成 A1 的材料核实。"
    plan["data"]["limitations"] = decision["data"]["limitations"] * 3 + ["Docker 部署细节尚需核实。"] * 2
    resume = {"summary": "已有 Python 项目，下一步完善可复现记录。", "career_profile": [
        {"field": "education", "value": "本科在读，计划研究生入学", "quote": EDUCATION},
        {"field": "major", "value": "示例专业", "quote": "示例专业"}]}
    state = {"input": {"preferences": "上海实习"}, "decision_input": inputs,
             "review": {"target_id": "T1", "constraints": constraints, "answers": {}},
             "results": {"resume_analysis": {"status": "ok", "data": resume},
                         "job_analysis": {"data": {"targets": inputs["targets"]}},
                         "career_decision": decision, "action_planning": plan}}
    return state, planning_input


class ReaderChecks(unittest.TestCase):
    def bundle(self, state):
        return build_report_bundle("offline-user", "report-012345abcdef", {}, state, "offline-model")

    def test_reader_copy_has_human_sources_and_raw_evidence_is_preserved(self):
        state, _ = fixture()
        original = deepcopy(state)
        bundle = self.bundle(state)
        text = bundle["report_document"]["markdown"]
        for marker in ("chunk-", "#record=", "C:/private", "[T1JD1]", "assessment.decision", "招聘记录内部键"):
            self.assertNotIn(marker, text)
        self.assertIn("示例企业 · 智能体开发实习生（上海）", text)
        self.assertIn("熟悉 Python", bundle["report_document"]["sections"]["appendix"]["markdown"])
        self.assertEqual(state, original)
        self.assertIn("#record=110", bundle["agent_results"]["job_analysis"]["data"]["targets"][0]["job_analysis"]["sources"][0]["file_path"])
        self.assertEqual(bundle["meta"]["content_validation"]["internal_references"], "passed")

    def test_profile_does_not_claim_known_resume_fields_are_missing(self):
        state, _ = fixture()
        text = self.bundle(state)["report_document"]["sections"]["personal_traits"]["markdown"]
        self.assertIn("本科在读", text)
        self.assertIn("示例专业", text)
        self.assertNotIn("未提供", text)
        self.assertNotIn("学历：未提供", text)

    def test_scope_is_consolidated_but_actionable_uncertainty_remains(self):
        state, _ = fixture()
        text = self.bundle(state)["report_document"]["markdown"]
        self.assertEqual(text.count(SCOPE_NOTE), 1)
        self.assertEqual(text.count("Docker 部署细节尚需核实。"), 1)
        self.assertNotIn("接口返回", text)
        self.assertNotIn("未请求招聘搜索", text)

    def test_irrelevant_sample_log_is_omitted_but_real_other_conditions_remain(self):
        state, _ = fixture()
        job = state["results"]["job_analysis"]["data"]["targets"][0]["job_analysis"]
        evidence = deepcopy(job["data"]["findings"][0]["evidence"])
        job["data"]["findings"] += [
            {"category": "other", "statement": "无关样本的 PCB 方向不宜并入本目标", "requirement": "unspecified", "evidence": evidence},
            {"category": "other", "statement": "每周到岗至少三天", "requirement": "required", "evidence": evidence}]
        text = self.bundle(state)["report_document"]["sections"]["matching_decision"]["markdown"]
        self.assertNotIn("PCB", text)
        self.assertIn("每周到岗至少三天", text)
        self.assertEqual(len(job["data"]["findings"]), 3)

    def test_real_model_names_and_language_levels_are_not_scrubbed(self):
        state, _ = fixture()
        presentation = ReportPresentation(state)
        self.assertEqual(presentation.clean("使用 DeepSeek R1，英语等级 C1。"), "使用 DeepSeek R1，英语等级 C1。")
        self.assertIn("简历原文", presentation.clean("依据 [R1]"))
        validate_reader_report("来源：https://example.invalid/jobs")
        with self.assertRaises(ValueError):
            validate_reader_report("来源：C:/private/jobs.txt")

    def test_cleanup_keeps_substantive_conditions_and_partial_read_warning(self):
        notes = reader_limitations(["保留接口返回的 chunk。Docker 部署细节仍需核实。"])
        self.assertEqual(notes, ["Docker 部署细节仍需核实。"])
        state, _ = fixture()
        state["results"]["resume_analysis"]["document"] = {"status": "partial"}
        self.assertIn("简历仅成功读取部分内容", self.bundle(state)["report_document"]["sections"]["appendix"]["markdown"])

    def test_reading_edition_is_narrative_and_omits_default_fields(self):
        state, _ = fixture()
        state["results"]["resume_analysis"]["data"]["score"] = 73.8
        report = self.bundle(state)["report_document"]
        self.assertEqual(report["reading_layout"], "narrative-v1")
        self.assertEqual(len(report["section_order"]), 6)
        before_sources = report["markdown"].split("## 参考依据与适用范围")[0]
        self.assertNotRegex(before_sources, r"(?m)^\s*[-*] ")
        self.assertNotIn("要求 1 ·", before_sources)
        self.assertNotIn("简历内容质量评分", before_sources)
        for field in ("前置任务：无", "支出：0", "阶段：", "交付物：", "验收标准：", "P1 ·"):
            self.assertNotIn(field, before_sources)
        self.assertIn("1. **确认项目贡献**", before_sources)
        self.assertIn("项目贡献清单", before_sources)
        self.assertIn("列出个人完成的 API 和验证方式", before_sources)
        self.assertEqual(before_sources.count("验证并完善 Python 项目成果"), 1)

    def test_real_costs_and_dependencies_are_kept_in_reading_edition(self):
        state, _ = fixture()
        tasks = state["results"]["action_planning"]["data"]["tasks"]
        tasks.append({**deepcopy(tasks[0]), "task_id": "A2", "week": 2, "title": "完成项目演示",
                      "depends_on": ["A1"], "cost": 5})
        state["review"]["constraints"]["budget"] = 20
        bundle = self.bundle(state)
        text = bundle["report_document"]["sections"]["gap_action_plan"]["markdown"]
        self.assertIn("预计支出 5 元", text)
        self.assertIn("先完成“确认项目贡献”", text)
        second = next(item for item in bundle["phase_plan"]["short_term"] if item.get("id") == "A2")
        self.assertEqual(second["depends_on"], ["A1"])

    def test_all_qualification_issues_survive_preparation_priority_limit(self):
        checks = {}
        for index in range(5):
            checks[f"hard-{index}"] = {"check_id": f"hard-{index}", "kind": "hard_condition", "status": "unknown",
                                       "importance": "required"}
        for index in range(6):
            checks[f"skill-{index}"] = {"check_id": f"skill-{index}", "kind": "capability", "status": "partial",
                                        "importance": "required"}
        _, selected = priority_checks(checks, [{"check_id": "skill-5"}])
        self.assertEqual(len([item for item in selected if item["kind"] == "hard_condition"]), 5)
        skill_ids = [item["check_id"] for item in selected if item["kind"] == "capability"]
        self.assertEqual(len(skill_ids), 3)
        self.assertEqual(skill_ids[0], "skill-5")


class TimelineChecks(unittest.TestCase):
    def test_sequential_education_is_compared_by_month(self):
        timeline = education_timeline_context(EDUCATION)
        self.assertEqual(timeline[0]["study_end_month"], "2027-06")
        self.assertEqual(timeline[0]["enrollment_month"], "2027-09")
        self.assertFalse(timeline[0]["overlaps"])
        self.assertTrue(verify_education_timeline_claims({"limitations": [FALSE_OVERLAP]}, EDUCATION))
        ocr = "计算机技术（推免）智能科学与技术（本科）2027.09入学2023.09-2027.06"
        self.assertFalse(education_timeline_context(ocr)[0]["overlaps"])

    def test_negations_and_genuine_project_overlaps_are_not_rejected(self):
        for statement in ("2027.06本科结束后2027.09入学，不存在重叠。",
                          "本科2023.09-2027.06与项目2025.05-2026.02时间存在重叠；研究生2027.09入学。"):
            self.assertFalse(verify_education_timeline_claims({"summary": statement}, EDUCATION))
        genuine = "本科2023.09-2027.10，研究生2027.09入学"
        self.assertTrue(education_timeline_context(genuine)[0]["overlaps"])
        self.assertFalse(verify_education_timeline_claims("本科2027.10结束与2027.09入学的时间存在重叠", genuine))

    def test_resume_and_decision_schema_reject_false_overlap(self):
        resume = {"summary": FALSE_OVERLAP, "dimensions": [], "experiences": [], "issues": [],
                  "recommendations": [], "missing_information": []}
        schema = ResumeAnalysisAgent(None).get_output_schema({"raw_resume": EDUCATION})
        with self.assertRaisesRegex(ValueError, "教育时间比较错误"):
            schema.model_validate(resume)
        state, planning_input = fixture()
        decision = deepcopy(state["results"]["career_decision"]["data"])
        decision["limitations"].append(FALSE_OVERLAP)
        schema = CareerDecisionAgent(None).get_output_schema(CareerDecisionAgent.prepare(planning_input["decision_input"]))
        with self.assertRaisesRegex(ValueError, "教育时间比较错误"):
            schema.model_validate(decision)

    def test_action_planning_repairs_false_overlap_before_publishing(self):
        import json
        state, payload = fixture()
        valid = deepcopy(state["results"]["action_planning"]["data"])
        invalid = deepcopy(valid)
        invalid["limitations"].append(FALSE_OVERLAP)
        model = ScriptedModel(responses=[json.dumps(item, ensure_ascii=False) for item in (invalid, valid)])
        result = asyncio.run(ReportActionPlanningAgent(model).arun(payload))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(model.seen), 2)
        self.assertIn("教育时间比较错误", model.seen[-1][-1].content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
