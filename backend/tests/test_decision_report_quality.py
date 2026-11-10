from copy import deepcopy
from datetime import date
from types import SimpleNamespace
import unittest

from backend.advisor.agents.career_decision import CareerDecisionAgent, verify_career_decision
from backend.advisor.utils.decision_grounding import verify_candidate_boundaries, model_attribution_questions
from backend.advisor.agents.action_planning import verify_action_plan
from backend.advisor.schemas.action_planning import ActionPlan
from backend.services.report.reader_sections import build_reader_sections
from backend.services.report.quality import validate_rendered_tasks, validate_analysis_for_publication


def payload(category="skill", requirement="required"):
    return {"raw_resume": "我完成过Python接口开发。", "targets": [{"target_id": "T1", "title": "应用开发", "job_analysis": {
        "status": "ok", "sources": [{"chunk_id": "s1", "content": "岗位要求：熟悉Python。SQL经验优先。", "file_path": "jd.txt#record=1"}],
        "data": {"summary": "应用岗位样本", "findings": [{"category": category, "statement": "熟悉Python", "requirement": requirement,
            "evidence": [{"chunk_id": "s1", "quote": "熟悉Python"}]}]}}}]}


def decision():
    return {"summary": "依据现有接口经验尝试", "assessments": [{"target_id": "T1", "decision": "recommended", "conclusion": "可以尝试",
        "checks": [{"check_id": "C1", "requirement": "熟悉Python", "kind": "capability", "importance": "required", "status": "supported",
            "job_evidence": [{"source_id": "T1JD1", "quote": "熟悉Python"}],
            "candidate_evidence": [{"source_id": "R1", "quote": "我完成过Python接口开发。"}], "reasoning": "已有接口实践"}]}]}


class DecisionQualityTests(unittest.TestCase):
    def test_overview_model_is_not_automatically_personal_implementation(self):
        raw = '## 项目\n项目采用模型（ModelAlpha-8B）。\n本人贡献：基于LoRA微调ModelBeta。'
        self.assertEqual(len(model_attribution_questions(raw)), 1)
        self.assertTrue(verify_candidate_boundaries({'summary': '你有LoRA微调ModelAlpha-8B的经验。'}, raw))
        self.assertEqual(verify_candidate_boundaries({'summary': '项目描述写ModelAlpha-8B，本人贡献写ModelBeta，两者用途待核实。'}, raw), [])
        self.assertEqual(model_attribution_questions(raw.replace('ModelBeta', 'ModelAlpha-8B')), [])

    def test_education_dates_do_not_identify_degree_level(self):
        self.assertTrue(verify_candidate_boundaries({"reasoning": "简历只显示本科阶段就读区间，最高学历未知。"}, "某大学，2022—2026"))
        self.assertEqual(verify_candidate_boundaries({"deliverable": "说明当前在读或已毕业状态。"}, "某大学"), [])

    def test_visible_work_fragment_cannot_prove_complete_years(self):
        item = decision()
        item["assessments"][0]["checks"][0].update(kind="hard_condition", requirement="三年工作经验", status="confirmed_gap", reasoning="已列实习不足三年。")
        self.assertTrue(any("完整工作年限" in error for error in verify_career_decision(item, CareerDecisionAgent.prepare(payload()))))

    def test_exploring_a_direction_does_not_prove_interest(self):
        item = decision()
        item["assessments"][0]["checks"][0].update(requirement="对AI有浓厚兴趣", reasoning="用户有明确的职业兴趣。")
        self.assertTrue(any("推断个人意愿" in error for error in verify_career_decision(item, CareerDecisionAgent.prepare(payload()))))

    def test_relevant_requirement_and_candidate_quote_pass(self):
        prepared = CareerDecisionAgent.prepare(payload())
        self.assertEqual(verify_career_decision(decision(), prepared), [])

    def test_summary_cannot_upgrade_unknown_into_confirmed_conflict(self):
        item = decision()
        item['summary'] = '当前材料存在明确资格差距。'
        self.assertTrue(any('摘要与检查项不一致' in error for error in verify_career_decision(item, CareerDecisionAgent.prepare(payload()))))
        item['summary'] = '不能据此判定明确资格差距，先核实。'
        self.assertEqual(verify_career_decision(item, CareerDecisionAgent.prepare(payload())), [])

    def test_unrelated_sources_cannot_become_requirements(self):
        prepared = CareerDecisionAgent.prepare(payload(category="other", requirement="unspecified"))
        self.assertTrue(verify_career_decision(decision(), prepared))
        empty = decision()
        empty["assessments"][0].update(decision="insufficient_information", checks=[])
        self.assertEqual(verify_career_decision(empty, prepared), [])

    def test_preferred_cannot_be_promoted_to_required(self):
        self.assertTrue(any("required" in error for error in verify_career_decision(
            decision(), CareerDecisionAgent.prepare(payload(requirement="preferred")))))

    def test_other_sentence_in_same_jd_is_not_approved_evidence(self):
        item = decision()
        item["assessments"][0]["checks"][0]["job_evidence"][0]["quote"] = "SQL经验优先"
        self.assertTrue(any("requirement_evidence" in error for error in verify_career_decision(item, CareerDecisionAgent.prepare(payload()))))

    def test_school_and_period_do_not_prove_degree(self):
        self.assertTrue(verify_candidate_boundaries({"summary": "学历为本科，已经毕业。"}, "某大学，计算机专业，2022—2026"))
        self.assertEqual(verify_candidate_boundaries({"summary": "学历层次尚未确认，是否已毕业待核实。"}, "某大学，计算机专业"), [])
        self.assertEqual(verify_candidate_boundaries({"summary": "已取得本科学位。"}, "已取得本科学位，学位证已提供。"), [])

    def test_preparation_cannot_become_attendance_fact(self):
        self.assertTrue(verify_candidate_boundaries({"comparison": "每周准备12小时不足以支撑需要长期到岗的实习。"}, ""))
        self.assertEqual(verify_candidate_boundaries({"comparison": "每周准备12小时不代表工作出勤能力，到岗条件需单独确认。"}, ""), [])

    def test_negated_degree_claim_and_job_requirement_are_not_candidate_assertions(self):
        self.assertEqual(verify_candidate_boundaries({"reasoning": "教育起止时间不能证明已取得学位，材料未补充学历取得情况，需要核实。"}, "某大学"), [])
        self.assertEqual(verify_candidate_boundaries({"requirement": "已取得本科学位", "reasoning": "资格未知"}, "某大学"), [])
        self.assertEqual(verify_candidate_boundaries({"reasoning": "材料没有说明已取得硕士学位，因此无法确认。", "deliverable": "说明已取得或计划取得的学位。"}, "某大学"), [])

    def test_read_recruitment_is_not_attached_to_every_target(self):
        data = payload()
        data["recruitment_search"] = {"status": "ok", "sources": [{"source_id": "S1", "read_state": "read", "title": "其他方向",
            "content": "其他岗位要求硕士", "url": "https://example.com"}], "data": {"findings": [{"source_id": "S1", "evidence_quotes": ["其他岗位要求硕士"]}]}}
        prepared = CareerDecisionAgent.prepare(data)
        self.assertEqual(len([source for source in prepared["sources"] if source["kind"] == "job"]), 1)
        self.assertEqual(len(prepared["recruitment_context"]["findings"]), 1)

    def test_unreported_qualification_is_unknown_not_confirmed_gap(self):
        item = decision()
        check = item["assessments"][0]["checks"][0]
        check.update(kind="hard_condition", status="confirmed_gap", reasoning="材料没有说明已取得硕士学位，因此存在明确差距。")
        errors = verify_career_decision(item, CareerDecisionAgent.prepare(payload()))
        self.assertTrue(any("不能判confirmed_gap" in error for error in errors))


class ReportQualityTests(unittest.TestCase):
    def test_individually_cited_skills_are_not_overwritten_in_profile(self):
        from backend.services.report.presentation import profile_lines
        lines = profile_lines({'career_profile': [{'field': 'skills', 'value': 'Python'}, {'field': 'skills', 'value': 'RAG'}, {'field': 'skills', 'value': 'OCR'}]}, {})
        self.assertEqual(lines, ['技能与实践方向：Python；RAG；OCR'])
    def test_equal_time_and_requirements_survive_under_distinct_tasks(self):
        tasks = [{"task_id": f"A{i}", "check_id": "C1", "title": f"实践任务{i}", "hours": 4, "week": 1,
                  "deliverable": f"成果{i}", "acceptance_criteria": f"验收{i}", "depends_on": [], "cost": 0} for i in (1, 2)]
        selected = {"target_id": "T1", "title": "应用开发", "job_analysis": {"data": {"findings": []}}}
        assessment = {"decision": "conditional", "conclusion": "先验证"}
        check = {"check_id": "C1", "status": "evidence_missing", "kind": "capability", "importance": "required", "requirement": "可验证的项目交付能力", "reasoning": "需要成果"}
        state = {"input": {}, "results": {"resume_analysis": {"data": {"recommendations": ["两个方向都从零复现"]}},
                 "career_decision": {"data": {}, "sources": []}, "action_planning": {"data": {"tasks": tasks}}},
                 "review": {"constraints": {"deadline": "2026-11-16", "weekly_hours": 12}, "answers": {}}}
        presentation = SimpleNamespace(clean=lambda text, **kwargs: text, targets=[selected], cite=lambda *args: None, appendix_sources=lambda: "")
        sections, _ = build_reader_sections(state, {}, presentation, selected, assessment, {"C1": check}, date(2026, 11, 10))
        text = sections["gap_action_plan"]["markdown"]
        self.assertEqual(text.count("预计 4 小时，2026-11-16 前完成"), 2)
        self.assertEqual(text.count("**对应要求：**"), 2)
        validate_rendered_tasks(text, tasks, date(2026, 11, 10), "2026-11-16")
        self.assertNotIn("两个方向都从零复现", sections["personal_traits"]["markdown"] if "personal_traits" in sections else "")
        broken = text.replace("预计 4 小时，2026-11-16 前完成。", "", 1)
        with self.assertRaises(ValueError):
            validate_rendered_tasks(broken, tasks, date(2026, 11, 10), "2026-11-16")

    def test_legacy_unsafe_rewrite_cannot_be_published(self):
        state = {"input": {"raw_resume": "项目负责人。"}, "results": {"resume_analysis": {"data": {"issues": [{
            "rewrite": "负责人（团队X人）：独立完成所有模块。", "evidence": []}]}}, "career_decision": {}, "action_planning": {}}}
        with self.assertRaisesRegex(ValueError, "事实校验"):
            validate_analysis_for_publication(state)


class PlanningQualityTests(unittest.TestCase):
    def test_unknown_years_cannot_become_unconditional_rejection_in_a_task(self):
        plan, prepared = self.fixture()
        prepared['assessment']['checks'][0].update(kind='hard_condition', status='unknown')
        plan.tasks[0].kind = 'clarify'
        plan.tasks[0].acceptance_criteria = '对要求2年以上经验的岗位明确标注为暂不匹配。'
        self.assertTrue(any('资格仍未知' in error for error in verify_action_plan(plan, prepared)))
        plan.tasks[0].acceptance_criteria = '若确认不满足经验门槛，标为不匹配；其他保留待核实。'
        self.assertEqual(verify_action_plan(plan, prepared), [])
    def fixture(self):
        prepared = {"assessment": {"decision": "recommended", "checks": [{"check_id": "C1", "kind": "capability", "status": "evidence_missing"}]},
            "target": {"target_type": "direction"}, "weeks": [{"week": 1, "days": 7, "hours_capacity": 12}],
            "constraints": {"weekly_hours": 12, "budget": 0}, "sources": []}
        plan = ActionPlan.model_validate({"summary": "验证项目", "tasks": [{"task_id": "A1", "check_id": "C1", "stage": "实践", "kind": "practice",
            "title": "搭建Agent", "week": 1, "hours": 2, "cost": 0, "depends_on": [], "deliverable": "可运行代码", "acceptance_criteria": "任务可复现"}],
            "reduced_plan": {"weekly_hours": 6, "keep_task_ids": ["A1"], "reason": "保留验证"}})
        return plan, prepared

    def test_unknown_practice_requires_existing_work_branch_and_free_path(self):
        plan, prepared = self.fixture()
        errors = verify_action_plan(plan, prepared)
        self.assertTrue(any("先检查已有实践" in error for error in errors))
        self.assertTrue(any("预算为零" in error for error in errors))
        plan.tasks[0].title = "先检查已有项目；没有才搭建最小Agent"
        plan.tasks[0].deliverable = "CPU本地检索与固定响应工具编排记录"
        self.assertEqual(verify_action_plan(plan, prepared), [])

    def test_available_preparation_does_not_prove_work_attendance(self):
        plan, prepared = self.fixture()
        plan.summary = "准备预算少，不足以支撑长期到岗实习。"
        self.assertTrue(any("工作出勤" in error for error in verify_action_plan(plan, prepared)))


if __name__ == "__main__":
    unittest.main()
