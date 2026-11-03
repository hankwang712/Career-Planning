from datetime import date, datetime, timedelta
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.report.development import months_after, task_horizon
from backend.services.report.workflow_report import build_report_bundle
from backend.scripts.check_report_workflow import RESUME, action_result, decision_result, job_result
from experiments.news_advisor.agents.resume import ResumeAnalysisAgent


class DevelopmentChecks(unittest.TestCase):
    def setUp(self):
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        inputs = {"raw_resume": RESUME, "targets": [{"target_id": "T1", "title": "Python 开发", "job_analysis": job_result()}]}
        decision = decision_result(inputs)
        constraints = {"start_date": today.isoformat(), "deadline": (today + timedelta(days=120)).isoformat(),
                       "weekly_hours": 8, "budget": 0, "student_stage": "exploration"}
        plan = action_result({"decision_input": inputs, "decision_result": decision, "target_id": "T1", "constraints": constraints})
        self.state = {"input": {"preferences": "希望探索工程方向"}, "review": {"target_id": "T1", "constraints": constraints}, "decision_input": inputs,
                      "results": {"resume_analysis": {"status": "ok", "data": {"summary": "已有 API 项目"}},
                                  "job_analysis": {"data": {"targets": inputs["targets"]}}, "career_decision": decision, "action_planning": plan}}

    def bundle(self):
        return build_report_bundle("offline-user", "report-012345abcdef", {}, self.state, "offline-model")

    def test_sections_evidence_and_real_dates(self):
        bundle = self.bundle()
        self.assertEqual(len(bundle["report_document"]["section_order"]), 10)
        self.assertIn("职业探索", bundle["report_document"]["sections"]["personal_traits"]["markdown"])
        self.assertIn("不是全市场招聘统计", bundle["report_document"]["sections"]["macro_environment"]["markdown"])
        self.assertIsNone(bundle["report_document"]["dashboard_summary"]["fit_score"])
        self.assertEqual(len(bundle["phase_plan"]["checkpoints"]), 3)
        action = next(item for item in bundle["phase_plan"]["short_term"] if item.get("is_action"))
        self.assertEqual(action["requirement"], "熟悉 Python")
        self.assertEqual(action["focus_points"], [])
        self.assertTrue(action["deliverable"] and action["acceptance_criteria"] and action["due_date"])

    def test_week_fourteen_is_midterm_and_calendar_boundaries(self):
        task = self.state["results"]["action_planning"]["data"]["tasks"][0]
        task["week"] = 14
        bundle = self.bundle()
        self.assertTrue(any(item.get("is_action") for item in bundle["phase_plan"]["mid_term"]))
        self.assertFalse(any(item.get("is_action") for item in bundle["phase_plan"]["long_term"]))
        self.assertEqual(months_after(date(2028, 1, 31), 1), date(2028, 2, 29))
        self.assertEqual(task_horizon(date(2026, 1, 31), date(2026, 4, 30)), "short")
        self.assertEqual(task_horizon(date(2026, 1, 31), date(2026, 5, 1)), "mid")

    def test_legacy_plan_is_not_fabricated_as_three_year_roadmap(self):
        self.state["results"]["action_planning"]["data"].pop("development_roadmap")
        bundle = self.bundle()
        self.assertFalse(bundle["phase_plan"]["mid_term"])
        self.assertIn("历史报告", bundle["report_document"]["sections"]["development_path"]["markdown"])

    def test_profile_quotes_must_exist_in_candidate_source(self):
        agent = ResumeAnalysisAgent(None)
        schema = agent.get_output_schema({"raw_resume": RESUME})
        data = {"summary": "项目经历", "dimensions": [], "experiences": [], "issues": [], "recommendations": [], "missing_information": [],
                "career_profile": [{"field": "skills", "value": "Python", "source": "raw_resume", "quote": "使用 Python 开发"}]}
        schema.model_validate(data)
        data["career_profile"][0]["quote"] = "精通 Java 与分布式架构"
        with self.assertRaises(ValueError):
            schema.model_validate(data)

    def test_tracker_preserves_action_details_and_counts_current_tasks(self):
        import contextlib
        import io
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        with contextlib.redirect_stderr(io.StringIO()):
            import server
        bundle = self.bundle()
        tracker = server._build_career_report_tracker(bundle)
        check = server._run_career_report_completeness_check(bundle)
        self.assertFalse(check["issues"], check["issues"])
        saved = bundle["report_document"]["sections"].pop("development_path")
        self.assertTrue(server._run_career_report_completeness_check(bundle)["issues"])
        bundle["report_document"]["sections"]["development_path"] = saved
        self.assertEqual(tracker["total_count"], 7)  # 1 current task + 3 roadmap actions + 3 reviews
        task = next(item for item in tracker["plan_items"] if item.get("is_action"))
        self.assertEqual(task["phase_key"], "short")
        self.assertEqual(task["hours"], 1)
        self.assertTrue(task["deadline"] and task["deliverable"] and task["acceptance_criteria"])
        task["status"] = "done"
        same = server._build_career_report_tracker(bundle, tracker)
        self.assertEqual(same["completed_count"], 1)
        bundle["meta"]["report_id"] = "report-ffffffffffff"
        self.assertEqual(server._build_career_report_tracker(bundle, tracker)["completed_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
