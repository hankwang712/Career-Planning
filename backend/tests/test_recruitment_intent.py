import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage

from backend.advisor.agents.recruitment_search import RecruitmentSearchAgent
from backend.advisor.radar.client import candidate_identity, match_score, normalize_job, search_jobs
from backend.advisor.utils.recruitment import (
    explicit_publication_window, explicit_recruitment_types, normalize_recruitment_types,
    recruitment_types_conflict,
)


class IntentTests(unittest.TestCase):
    def test_unrestricted_channels_and_qualification_warnings(self):
        self.assertEqual(explicit_recruitment_types("校招或社招不限，不默认满足校招届别或在校实习要求"), set())
        self.assertEqual(explicit_recruitment_types("寻找大模型应用开发，不要默认具备实习资格"), set())
        self.assertEqual(explicit_recruitment_types("只找实习，不考虑社招"), {"实习"})
        self.assertEqual(explicit_recruitment_types("寻找校招或社招岗位"), {"校招", "社招"})

    def test_batch_normalization_and_unknown_is_not_conflict(self):
        self.assertEqual(normalize_recruitment_types(["27届暑期实习", "日常实习"]), {"实习"})
        self.assertFalse(recruitment_types_conflict({"校招"}, ["27届秋招正式批"]))
        self.assertFalse(recruitment_types_conflict({"实习"}, ["日常实习"]))
        self.assertFalse(recruitment_types_conflict({"校招"}, ["未注明"]))
        self.assertFalse(recruitment_types_conflict(set(), ["27届提前批"]))
        self.assertTrue(recruitment_types_conflict({"社招"}, ["27届暑期实习"]))
        self.assertTrue(recruitment_types_conflict({"校招"}, ["27届春招实习"]))
        self.assertFalse(recruitment_types_conflict({"春招"}, ["27届春招实习"]))

    def test_only_positive_publication_requests_create_window(self):
        self.assertFalse(explicit_publication_window("公告日期未知可单列，不要冒充近期发布或仍开放"))
        self.assertFalse(explicit_publication_window("发布时间不限，不要求近期发布"))
        self.assertFalse(explicit_publication_window("不要只找近期发布的岗位"))
        self.assertFalse(explicit_publication_window("优先近期发布的，旧公告也可以单列"))
        self.assertTrue(explicit_publication_window("只找最近一个月发布的岗位"))
        self.assertTrue(explicit_publication_window("找2026-10-01之后发布的招聘公告"))
        self.assertFalse(explicit_publication_window("2026-10-01之后可以到岗"))

    def test_generic_development_does_not_match_specialist_direction(self):
        job = normalize_job({"company": "A", "role": "web前端开发工程师", "city": "杭州"})
        self.assertEqual(match_score(job, ["多模态算法工程师", "大模型应用开发工程师"]), 0)
        job["role"] = "多模态算法工程师"
        self.assertGreater(match_score(job, ["多模态算法工程师"]), 0)
        job["role"] = "Agent开发工程师"
        self.assertGreater(match_score(job, ["大模型应用开发工程师"]), 0)
        job["role"] = "大模型后训练算法工程师"
        self.assertEqual(match_score(job, ["大模型应用开发工程师"]), 0)
        job["role"] = "Python实习生"
        job["description"] = "开发RAG知识库应用，维护Agent工作流"
        self.assertGreater(match_score(job, ["大模型应用开发工程师"]), 0)


class RecallTests(unittest.IsolatedAsyncioTestCase):
    async def test_direction_city_coverage_and_exclusion(self):
        jobs = [normalize_job({"company": str(i), "role": role, "city": city})
                for i, (role, city) in enumerate([
                    ("大模型应用开发工程师", "上海"), ("大模型应用开发工程师", "上海"),
                    ("多模态算法工程师", "杭州"), ("多模态算法工程师", "上海"),
                    ("大模型应用开发工程师", "杭州")])]
        async def sync(**kwargs):
            return {"jobs": jobs, "status": "cached", "mode": "live_cache", "limitations": []}
        with patch("backend.advisor.radar.client.sync_jobs", sync), patch("backend.advisor.radar.client.read_jobhunter_jobs", return_value={"jobs": [], "status": "empty", "limitations": []}):
            intent = {"roles": ["大模型应用开发工程师", "多模态算法工程师"], "cities": ["杭州", "上海"]}
            first = await search_jobs(intent, "", limit=4, read_limit=0)
            self.assertEqual({(j["role"], j["city"]) for j in first["jobs"]},
                {(role, city) for role in intent["roles"] for city in intent["cities"]})
            intent["_excluded_records"] = [list(candidate_identity(j)) for j in first["jobs"]]
            second = await search_jobs(intent, "", limit=4, read_limit=0)
            self.assertFalse({candidate_identity(j) for j in first["jobs"]} & {candidate_identity(j) for j in second["jobs"]})

    async def run_pipeline(self, request, *, days=None, tool_budget=8, direction_match="direct"):
        calls = []

        class Model:
            def bind(self, **kwargs):
                return self

            async def ainvoke(self, messages, config=None):
                payload = json.loads(messages[-1].content)
                if "sources" not in payload:
                    result = {"intent": {"roles": ["大模型应用开发工程师", "多模态算法工程师"],
                        "cities": ["杭州", "上海"], "recruitment_types": [], "days": 30},
                        "queries": [{"query": "大模型应用开发", "purpose": "应用方向"}, {"query": "多模态算法", "purpose": "算法方向"}]}
                else:
                    result = {"decisions": [{"source_id": source["source_id"], "verdict": "qualified",
                        "reason": "方向和地点符合", "evidence_quote": source["content"].splitlines()[1],
                        "recruitment_types": ["27届秋招正式批"], "direction_match": direction_match} for source in payload["sources"]]}
                return AIMessage(content=json.dumps(result, ensure_ascii=False))

        async def recall(arguments, **kwargs):
            calls.append(arguments)
            job = normalize_job({"company": "A" + str(len(calls)), "role": "多模态算法工程师", "city": "杭州",
                "batch": "27届秋招正式批", "url": "https://example.com/job/" + str(len(calls)), "published_at": "2020-01-01"})
            return {"jobs": [job], "candidates": [{"page": 1, "rank": 1, "title": job["role"], "status": "retained", "reason": "待核实"}],
                "total_records": 100, "matched_records": 20, "status": "cached", "mode": "live_cache", "fetched_at": None, "limitations": []}

        async def verify(arguments, **kwargs):
            for job in arguments["jobs"]:
                job["detail_state"] = "read"
            return {"jobs": arguments["jobs"]}

        from backend.advisor.agents import radar_pipeline
        with patch.object(radar_pipeline, "search_recruitment_radar", SimpleNamespace(ainvoke=recall)), \
             patch.object(radar_pipeline, "verify_recruitment_radar_candidates", SimpleNamespace(ainvoke=verify)):
            result = await RecruitmentSearchAgent(Model(), max_tool_calls=tool_budget).arun({"request": request, "limit": 6, "days": days})
        self.assertEqual(result["status"], "ok", result.get("error"))
        return result, calls

    async def test_pipeline_does_not_reject_old_or_verbose_batches_without_user_restriction(self):
        result, calls = await self.run_pipeline("杭州或上海的多模态岗位。校招或社招不限，不默认满足校招届别或在校实习要求。不要冒充近期发布或仍开放。")
        self.assertEqual(result["search_plan"]["intent"]["recruitment_types"], [])
        self.assertIsNone(result["search_plan"]["intent"]["days"])
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["coverage"]["queries_executed"], 3)
        self.assertTrue(calls[1]["intent"]["_excluded_records"])
        self.assertEqual(len(result["data"]["findings"]), 3)
        self.assertNotIn("时间要求", result["data"]["summary"])

    async def test_explicit_window_remains_hard_constraint(self):
        result, _ = await self.run_pipeline("寻找杭州或上海最近7天发布的岗位", days=7)
        self.assertEqual(result["data"]["findings"], [])
        self.assertTrue(all(source["excluded_reason"] == "原文发布日期不符合用户要求的时间范围" for source in result["sources"]))

    async def test_single_tool_budget_can_still_return_unread_leads(self):
        result, calls = await self.run_pipeline("寻找杭州多模态算法岗位", tool_budget=1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(result["data"]["findings"])
        self.assertEqual(result["sources"][0]["read_state"], "listing")

    async def test_adjacent_responsibilities_do_not_become_target_opportunities(self):
        result, _ = await self.run_pipeline("寻找大模型应用开发或VLM算法岗位", direction_match="adjacent")
        self.assertFalse(result["data"]["findings"])
        self.assertTrue(all("主要职责与目标方向仅相邻" in source["excluded_reason"] for source in result["sources"]))


if __name__ == "__main__":
    unittest.main()
