"""Offline regression checks; collection fixtures never access recruiting sites."""
from concurrent.futures import ThreadPoolExecutor
from functools import wraps
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flask import Flask, jsonify, session
from pydantic import ValidationError
from services import auth, db
from services.job_market.api import create_blueprint
from services.job_market.collector import CollectionSettings, Collector
from services.job_market.store import MarketStore, after, canonical_url, normalize, salary_range


class MarketFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = MarketStore(Path(self.temp.name) / "market.db")
        self.config = CollectionSettings(sources=["ncss"]).model_dump()
        self.store.save_settings(self.config, due=after(-10))

    def tearDown(self):
        self.temp.cleanup()

    def claim(self):
        run_id = self.store.claim_run(self.config)
        self.assertIsNotNone(run_id)
        return run_id

    def job(self, **fields):
        return {"job_title": "Python 开发实习生", "company_name": "示例公司", "location": "上海", "salary": "150-200元/天",
                "education": "本科", "job_type": "intern", "job_desc": "Python 与 SQL 数据分析", "job_url": "https://example.com/jobs/42", **fields}

    def ingest(self, **fields):
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job(**fields)])
        self.store.finish(run_id, "succeeded")
        return run_id


class StoreChecks(MarketFixture):
    def test_callbacks_deduplicate_and_keep_enrichment(self):
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job(job_desc="")])
        self.store.ingest(run_id, "ncss", [self.job()])
        self.store.ingest(run_id, "ncss", [self.job(job_desc="")])
        self.assertEqual(self.store.jobs({})["total"], 1)
        self.assertEqual(self.store.runs()[0]["counts"], {"new": 1})
        self.assertIn("Python", self.store.jobs({})["items"][0]["job_desc"])

    def test_repeated_collection_is_seen_then_actual_change(self):
        self.ingest()
        original = self.store.jobs({})["items"][0]
        self.ingest()
        self.assertEqual(self.store.runs()[0]["counts"], {"seen": 1})
        self.ingest(salary="180-220元/天")
        self.assertEqual(self.store.jobs({})["total"], 1)
        self.assertEqual(self.store.runs()[0]["counts"], {"changed": 1})
        self.assertEqual(self.store.jobs({})["items"][0]["first_seen"], original["first_seen"])

    def test_source_ids_keep_identity_when_title_changes(self):
        self.ingest(source_record_id="42")
        self.ingest(source_record_id="42", job_title="Python 后端实习生")
        self.assertEqual(self.store.jobs({})["total"], 1)
        self.assertEqual(self.store.jobs({})["items"][0]["job_title"], "Python 后端实习生")

    def test_listing_urls_do_not_merge_different_jobs(self):
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job(job_url="https://example.com/jobs"), self.job(job_url="https://example.com/jobs", job_title="产品实习生")])
        self.assertEqual(self.store.jobs({})["total"], 2)

    def test_url_validation_tracking_and_hash_routes(self):
        self.assertEqual(canonical_url("https://example.com/jobs?id=42&utm_source=x#section"), "https://example.com/jobs?id=42")
        self.assertEqual(canonical_url("https://example.com/#/jobs/42"), "https://example.com/#/jobs/42")
        for url in ("javascript:alert(1)", "file:///private", "https://[", "https://user:secret@example.com/"):
            self.assertIsNone(normalize(self.job(job_url=url), "ncss"))
        row = normalize(self.job(job_desc="<p>Python</p><script>secret()</script>"), "ncss")
        self.assertNotIn("secret", row["job_desc"])

    def test_salary_units_and_unknown_values_remain_separate(self):
        self.assertEqual(salary_range("10K-20K"), (10000, 20000, "month"))
        self.assertEqual(salary_range("1.5-2万/月"), (15000, 20000, "month"))
        self.assertEqual(salary_range("20-30万/年"), (200000, 300000, "year"))
        self.assertEqual(salary_range("150-200/天"), (150, 200, "day"))
        for value in ("面议", "薪资10000起", "20-30万", "", "10000", "30K-10K"):
            self.assertIsNone(salary_range(value)[0])
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job(), self.job(source_record_id="monthly", salary="10-20K"), self.job(source_record_id="annual", salary="20-30万/年"), self.job(source_record_id="unknown", salary="面议")])
        stats = self.store.stats({})
        self.assertEqual(stats["salary"]["month"], {"count": 1, "median_midpoint": 15000})
        self.assertEqual(stats["salary"]["day"]["median_midpoint"], 175)
        self.assertEqual(stats["salary"]["year"]["count"], 1)

    def test_filters_and_statistics_use_the_same_population(self):
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job(), self.job(source_record_id="bj", location="北京", salary="20K-30K", industry="互联网")])
        filters = {"location": "上海", "salary_unit": "day"}
        self.assertEqual(self.store.jobs(filters)["total"], self.store.stats(filters)["total"])
        self.assertEqual(self.store.jobs({"q": "%"})["total"], 0)
        self.assertEqual(self.store.jobs({"q": "' OR 1=1 --"})["total"], 0)
        self.assertEqual(self.store.jobs({"date_from": "2026-01-01"})["total"], 0)
        self.assertEqual(self.store.jobs({"salary_unit": "month", "salary_min": 15000})["total"], 1)
        self.assertEqual(self.store.stats({})["skills"][0]["count"], 2)

    def test_single_collection_lease_is_atomic_across_connections(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.claim_run(self.config), range(4)))
        self.assertEqual(sum(bool(value) for value in results), 1)

    def test_expired_worker_is_recovered_and_no_longer_accepts_jobs(self):
        old = self.claim()
        with self.store.connect() as conn:
            conn.execute("UPDATE runs SET lease_until=? WHERE id=?", (after(-1), old))
        new = self.claim()
        self.assertNotEqual(old, new)
        self.assertEqual(self.store.ingest(old, "ncss", [self.job()]), 0)
        self.assertEqual(self.store.jobs({})["total"], 0)
        old_run = next(row for row in self.store.runs() if row["id"] == old)
        self.assertEqual(old_run["sources"][0]["status"], "interrupted")

    def test_disabled_schedule_and_persisted_due_date(self):
        self.store.save_settings({**self.config, "enabled": False}, due=after(-10))
        self.assertIsNone(self.store.claim_run(self.config, require_due=True))
        due = after(3600)
        self.store.save_settings(self.config, due=due)
        other = Collector(self.store, directory=self.temp.name)
        self.assertEqual(other.store.settings()["next_run_at"], due)
        self.assertIsNone(self.store.claim_run(self.config, require_due=True))

    def test_cancel_fences_late_data_and_keeps_prior_records(self):
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job()])
        self.store.cancel()
        self.assertEqual(self.store.ingest(run_id, "ncss", [self.job(source_record_id="late")]), 0)
        self.assertEqual(self.store.jobs({})["total"], 1)

    def test_failure_retains_prior_jobs_and_does_not_claim_closure(self):
        self.ingest()
        config = {**self.config, "sources": ["ncss", "api"]}
        def source(run_id, key, _):
            if key == "ncss":
                self.store.ingest(run_id, key, [self.job()])
                return "succeeded", "OK"
            return "failed", "Source unavailable"
        worker = Collector(self.store, source_runner=source, directory=self.temp.name)
        run_id = self.store.claim_run(config)
        worker.collect(run_id, config)
        run = next(row for row in self.store.runs() if row["id"] == run_id)
        self.assertEqual(run["status"], "partial")
        self.assertEqual(self.store.jobs({})["total"], 1)
        self.assertNotIn("closed", self.store.jobs({})["items"][0])

    def test_successful_process_with_no_valid_records_is_not_success(self):
        worker = Collector(self.store, source_runner=lambda *args: ("succeeded", "OK"), directory=self.temp.name)
        run_id = self.claim()
        worker.collect(run_id, self.config)
        self.assertEqual(self.store.runs()[0]["status"], "failed")
        self.assertEqual(self.store.runs()[0]["sources"][0]["status"], "failed")


class ApiChecks(MarketFixture):
    def setUp(self):
        super().setUp()
        self.original_db, self.original_dir = db.DB_PATH, db.APP_DATA_DIR
        self.original_conn = getattr(db._local, "conn", None)
        db._local.conn = None
        db.DB_PATH = str(Path(self.temp.name) / "auth.db")
        db.APP_DATA_DIR = Path(self.temp.name)
        db.init_db()
        self.app = Flask(__name__)
        self.app.config["TESTING"] = True
        auth.init_app(self.app)
        self.worker = Collector(self.store, source_runner=lambda *args: ("empty", "No results"), directory=self.temp.name)
        def user():
            name = session.get("qa_user")
            return {"username": name, "role": "super_admin" if name == "admin" else "user"} if name else None
        def guard(admin=False):
            def decorate(fn):
                @wraps(fn)
                def wrapped(*args, **kwargs):
                    identity = user()
                    if not identity:
                        return jsonify(message="Login required"), 401
                    if admin and identity["role"] != "super_admin":
                        return jsonify(message="Admin only"), 403
                    return fn(*args, **kwargs)
                return wrapped
            return decorate
        self.app.register_blueprint(create_blueprint(self.worker, guard(), guard(True), user))
        self.client = self.app.test_client()
        self.login("user")

    def tearDown(self):
        db._get_conn().close()
        db._local.conn = self.original_conn
        db.DB_PATH, db.APP_DATA_DIR = self.original_db, self.original_dir
        super().tearDown()

    def login(self, name):
        with self.client.session_transaction() as session:
            session["qa_user"] = name
            session["csrf_token"] = "job-csrf"

    def test_api_auth_admin_and_csrf(self):
        response = self.client.get("/api/job-market/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["can_manage"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.post("/api/job-market/collect", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/job-market/collect", json={}, headers={"X-CSRF-Token": "job-csrf"}).status_code, 403)
        with self.client.session_transaction() as session:
            session.pop("qa_user")
        self.assertEqual(self.client.get("/api/job-market/jobs").status_code, 401)

    def test_api_rejects_incomparable_and_invalid_filters(self):
        for query in ("salary_min=10", "salary_min=30&salary_max=10&salary_unit=month", "page=-1", "days=banana", "source=unknown", "date_from=2026-11-05&date_to=2026-01-01"):
            self.assertEqual(self.client.get("/api/job-market/jobs?" + query).status_code, 400, query)
        with self.assertRaises(ValidationError):
            CollectionSettings(sources=["ncss", "ncss"])
        with self.assertRaises(ValidationError):
            CollectionSettings(interval_hours=0)

    def test_admin_settings_are_persistent_and_validated(self):
        self.login("admin")
        settings = {**self.config, "interval_hours": 12, "enabled": False}
        response = self.client.put("/api/job-market/settings", json=settings, headers={"X-CSRF-Token": "job-csrf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/job-market/status").json["settings"]["interval_hours"], 12)
        self.assertEqual(self.client.put("/api/job-market/settings", json={"sources": ["private-url"]}, headers={"X-CSRF-Token": "job-csrf"}).status_code, 400)

    def test_export_applies_filters_and_does_not_create_formulas(self):
        run_id = self.claim()
        self.store.ingest(run_id, "ncss", [self.job(company_name="=HYPERLINK(\"https://example.com\")"), self.job(location="北京", source_record_id="bj")])
        response = self.client.get("/api/job-market/export?location=上海")
        self.assertEqual(response.status_code, 200)
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(response.data))
        sheet = workbook["岗位样本"]
        self.assertEqual(sheet.max_row, 2)
        self.assertEqual(sheet["B2"].data_type, "s")
        self.assertTrue(sheet["B2"].value.startswith("'="))
        self.assertIn("统计说明", workbook.sheetnames)


if __name__ == "__main__":
    unittest.main()
