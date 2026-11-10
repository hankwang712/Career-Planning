import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.advisor.radar import client
from backend.advisor.radar.job_sources import canonical_url, deduplicate_jobs, read_jobhunter_jobs
from backend.services.job_market.store import MarketStore


def lead(**changes):
    return {**client.normalize_job({"company": "示例科技", "role": "后端工程师", "city": "杭州",
        "batch": "27届暑期实习", "url": "https://careers.example.com/jobs/42", "description": "",
        "updated_at": "2026-11-01"}, source_type="aggregate", source_name="Radar"), **changes}


class SourceMergeTests(unittest.TestCase):
    def test_merge_preserves_origins_and_uses_complete_record_without_mutation(self):
        radar = lead()
        market = lead(company=" 示例科技 ", batch="实习", source_type="jobhunter", source_name="JobHunter",
                      description="负责后端接口开发。", published_at="2026-10-20", updated_at="2026-11-10",
                      url="https://careers.example.com/jobs/42?utm_source=radar")
        merged = deduplicate_jobs([radar, market])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["source_type"], "jobhunter")
        self.assertEqual(merged[0]["batch"], "27届暑期实习")
        self.assertEqual(merged[0]["published_at"], "2026-10-20")
        self.assertEqual({row["source_name"] for row in merged[0]["provenance"]}, {"Radar", "JobHunter"})
        self.assertNotIn("provenance", radar)
        self.assertEqual(merged[0]["detail_state"], "not_read")

    def test_do_not_collapse_distinct_vacancies(self):
        variants = [lead(), lead(city="上海"), lead(batch="28届暑期实习"), lead(batch="27届校招"),
                    lead(batch="27届寒假实习"), lead(url="https://careers.example.com/jobs/43"),
                    lead(role="前端工程师"), lead(company="其他公司")]
        self.assertEqual(len(deduplicate_jobs(variants)), len(variants))

    def test_shared_listing_link_does_not_merge_roles_or_cities(self):
        url = "https://example.com/careers#/jobs"
        self.assertEqual(len(deduplicate_jobs([lead(url=url), lead(url=url, role="前端工程师"), lead(url=url, city="上海")])), 3)

    def test_preserve_hash_and_functional_query_ids(self):
        self.assertEqual(canonical_url("http://example.com/jobs/?utm_source=a&jobId=42&source=b#/job/42?sourceToken=x"),
                         "https://example.com/jobs?jobId=42#/job/42")
        self.assertEqual(len(deduplicate_jobs([lead(url="https://example.com/jobs?jobId=42"),
                                              lead(url="https://example.com/jobs?jobId=43")])), 2)
        self.assertEqual(len(deduplicate_jobs([lead(url="https://example.com/#/job/42"),
                                              lead(url="https://example.com/#/job/43")])), 2)

    def test_snapshot_date_is_not_copied_to_undated_live_record(self):
        merged = deduplicate_jobs([lead(source_type="snapshot", published_at="2024-01-01"),
                                   lead(source_type="jobhunter", published_at="", updated_at="2026-11-10")])[0]
        self.assertEqual(merged["published_at"], "")

    def test_read_existing_store_without_changing_records(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "market.sqlite3"
            store = MarketStore(path)
            run = store.claim_run({"sources": ["api"], "interval_hours": 6}, "manual")
            store.ingest(run, "api", [{"job_title": "后端工程师", "company_name": "示例科技",
                "job_url": "https://careers.example.com/jobs/42", "location": "杭州", "job_type": "intern",
                "publish_date": "2026-10-20", "job_desc": "开发后端服务。"}])
            before = store.jobs({"days": 0})
            result = read_jobhunter_jobs(path)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["jobs"][0]["published_at"], "2026-10-20")
            self.assertEqual(result["jobs"][0]["batch"], "实习")
            self.assertEqual(result["jobs"][0]["detail_state"], "not_read")
            self.assertEqual(before, store.jobs({"days": 0}))
            self.assertEqual(read_jobhunter_jobs(path, limit=0)["jobs"], [])
            self.assertTrue(any("上限" in note or "最多" in note for note in read_jobhunter_jobs(path, limit=0)["limitations"]))

    def test_missing_or_invalid_store_is_nonfatal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.sqlite3"
            self.assertEqual(read_jobhunter_jobs(path)["status"], "not_collected")
            self.assertFalse(path.exists())
            path.write_text("invalid database")
            self.assertEqual(read_jobhunter_jobs(path)["status"], "unavailable")


class CombinedSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_combined_search_deduplicates_before_limit_and_keeps_dates(self):
        radar = {"jobs": [lead()], "status": "cached", "limitations": [], "mode": "live_cache"}
        with patch.object(client, "sync_jobs", AsyncMock(return_value=radar)), patch.object(client, "read_jobhunter_jobs", return_value={
            "jobs": [lead(source_type="jobhunter", source_name="JobHunter", snapshot_at="2026-11-10", source_record_id="1", published_at_source="unverified"),
                     lead(role="后端开发工程师", source_type="jobhunter", source_name="JobHunter", snapshot_at="2026-11-10", source_record_id="2", published_at_source="unverified")],
            "status": "ok", "limitations": []}):
            result = await client.search_jobs({"roles": ["后端"]}, "后端", limit=2, read_limit=0)
        self.assertEqual(len(result["jobs"]), 2)
        self.assertEqual(result["merge_stats"]["duplicates_removed"], 1)
        self.assertEqual(result["merge_stats"]["jobhunter_records"], 2)
        self.assertEqual(result["jobs"][0]["published_at"], "")
        self.assertTrue(any(len(job["provenance"]) == 2 for job in result["jobs"]))

    async def test_radar_failure_still_returns_market_candidates(self):
        with patch.object(client, "sync_jobs", AsyncMock(side_effect=OSError("unavailable"))), \
             patch.object(client, "read_jobs", return_value={"jobs": [], "mode": "snapshot", "limitations": []}), \
             patch.object(client, "read_jobhunter_jobs", return_value={"status": "ok", "limitations": [], "jobs": [
                 lead(source_name="JobHunter", snapshot_at="2026-11-10", source_record_id="1", published_at_source="unverified")]}):
            result = await client.search_jobs({"roles": ["后端"]}, "后端", read_limit=0)
        self.assertEqual(len(result["jobs"]), 1)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["jobs"][0]["source_type"], "jobhunter")

    async def test_old_publication_not_rescued_by_recent_collection(self):
        with patch.object(client, "sync_jobs", AsyncMock(return_value={"jobs": [], "status": "cached", "limitations": [], "mode": "live_cache"})), \
             patch.object(client, "read_jobhunter_jobs", return_value={"status": "ok", "limitations": [], "jobs": [
                 lead(source_name="JobHunter", snapshot_at="2026-11-10", source_record_id="1", published_at="2020-01-01", published_at_source="jobhunter_listing")]}):
            result = await client.search_jobs({"roles": ["后端"], "published_after": "2026-10-01"}, "后端", read_limit=0)
        self.assertEqual(result["jobs"], [])


if __name__ == "__main__":
    unittest.main()
