"""Offline checks for ownership, source lifetimes, evidence and concurrent editing."""
from functools import wraps
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify
from services import auth, db
from services.career import create_blueprint


class CareerProfileChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_path = db.DB_PATH
        self.original_directory = db.APP_DATA_DIR
        self.original_conn = getattr(db._local, "conn", None)
        db._local.conn = None
        db.DB_PATH = str(Path(self.temp.name) / "app.db")
        db.APP_DATA_DIR = Path(self.temp.name)
        db.init_db()
        with db._get_conn() as conn:
            for name in ("alice", "bob"):
                conn.execute("INSERT INTO users(username,password_hash,display_name) VALUES(?,?,?)", (name, "test-hash", name))
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="career-tests")
        auth.init_app(self.app)
        self.states = {}
        self.memories = []

        def login_required(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if not auth.current_user():
                    return jsonify(message="请先登录"), 401
                return fn(*args, **kwargs)
            return wrapped

        self.app.register_blueprint(create_blueprint(login_required, auth.current_user,
            lambda owner: self.states.get(owner, {}), lambda owner: self.memories if owner == "alice" else []))
        self.client = self.app.test_client()
        self.login("alice")

    def tearDown(self):
        db._get_conn().close()
        db._local.conn = self.original_conn
        db.DB_PATH, db.APP_DATA_DIR = self.original_path, self.original_directory
        self.temp.cleanup()

    def login(self, owner):
        import time
        with self.app.test_request_context():
            token = "test-token-" + owner
            digest = auth.digest(token)
        with db._get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO auth_sessions VALUES(?,?,?,?)", (digest, owner, time.time(), time.time() + 3600))
        with self.client.session_transaction() as session:
            session["auth_token"] = token
            session["csrf_token"] = "test-csrf"

    def write(self, path, body, method="POST"):
        return self.client.open("/api/career-profile/" + path, method=method,
            json=body, headers={"X-CSRF-Token": "test-csrf"})

    def skill(self, name="LangGraph"):
        response = self.write("skills", {"name": name})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json["data"]

    def get(self):
        response = self.client.get("/api/career-profile")
        self.assertEqual(response.status_code, 200, response.json)
        return response.json["data"]

    def test_auth_csrf_and_private_headers(self):
        self.assertEqual(self.client.post("/api/career-profile/skills", json={"name": "X"}).status_code, 403)
        response = self.client.get("/api/career-profile")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Workspace-Owner"], "alice")
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get("/api/career-profile").status_code, 401)

    def test_profile_partial_updates_do_not_overwrite_other_entities(self):
        skill = self.skill()
        response = self.write("profile", {"display_name": "Alice", "city": "上海"}, "PUT")
        self.assertEqual(response.status_code, 200)
        profile = response.json["data"]
        response = self.write("profile/" + profile["id"], {"display_name": "Alice", "city": "杭州", "version": 1}, "PUT")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get()["skills"][0]["id"], skill["id"])
        history = self.client.get("/api/career-profile/history/" + profile["id"]).json["data"]
        self.assertEqual([row["version"] for row in history], [2, 1])
        self.assertEqual(history[1]["snapshot"]["city"], "上海")

    def test_stale_edits_and_deletes_are_rejected(self):
        skill = self.skill()
        path = "skills/" + skill["id"]
        self.assertEqual(self.write(path, {"name": "LangGraph", "category": "AI", "version": 1}, "PUT").status_code, 200)
        self.assertEqual(self.write(path, {"name": "overwritten", "version": 1}, "PUT").status_code, 409)
        self.assertEqual(self.write(path, {"version": 1}, "DELETE").status_code, 409)
        self.assertEqual(self.get()["skills"][0]["category"], "AI")

    def test_ownership_covers_linked_evidence_and_history(self):
        skill = self.skill()
        self.login("bob")
        self.assertEqual(self.get()["skills"], [])
        self.assertEqual(self.client.get("/api/career-profile/history/" + skill["id"]).json["data"], [])
        self.assertEqual(self.write("skills/" + skill["id"], {"name": "stolen", "version": 1}, "PUT").status_code, 404)
        self.assertEqual(self.write("evidence", {"skill_id": skill["id"], "kind": "self_report", "title": "X"}).status_code, 404)

    def test_links_cannot_claim_verified_capability(self):
        skill = self.skill()
        payload = {"skill_id": skill["id"], "kind": "experience_support", "title": "项目", "description": "实现流程节点与状态持久化", "url": "https://example.com/project"}
        self.assertEqual(self.write("evidence", payload).status_code, 200)
        self.assertEqual(self.get()["skills"][0]["evidence_level"], "experience_support")
        for invalid in ("artifact_verified", "assessed"):
            self.assertEqual(self.write("evidence", {**payload, "kind": invalid}).status_code, 400)
        for url in ("javascript:alert(1)", "https://[", "file:///private"):
            self.assertEqual(self.write("evidence", {**payload, "url": url}).status_code, 400)
        self.assertEqual(self.write("evidence", {**payload, "description": ""}).status_code, 400)

    def test_duplicate_skills_validation_and_cascade(self):
        skill = self.skill()
        self.assertEqual(self.write("skills", {"name": " langgraph "}).status_code, 409)
        self.assertEqual(self.write("skills", {"name": " ", "owner": "bob"}).status_code, 400)
        self.assertEqual(self.write("evidence", {"skill_id": skill["id"], "kind": "self_report", "title": "声明"}).status_code, 200)
        self.assertEqual(self.write("skills/" + skill["id"], {"version": 1}, "DELETE").status_code, 200)
        self.assertEqual(self.get()["evidence"], [])

    def test_resume_import_is_idempotent_and_forgetting_propagates(self):
        self.states["alice"] = {"resume_profile": {"document_id": "resume-1", "original_file_name": "简历.pdf", "uploaded_at": 1793800000,
            "structured_resume": {"skills": ["LangGraph"], "projects": [{"name": "职业助手", "description": "编排工作流"}]}}}
        first = self.get()
        second = self.get()
        self.assertEqual(first, second)
        self.assertEqual(len(first["resumes"]), 1)
        self.assertEqual(first["skills"][0]["evidence_level"], "self_report")
        self.assertEqual(self.write("evidence/" + first["evidence"][0]["id"], {"version": 1}, "DELETE").status_code, 409)
        self.states["alice"] = {}
        final = self.get()
        self.assertEqual([len(final[key]) for key in ("resumes", "evidence", "skills", "entries")], [0, 0, 0, 0])

    def test_resume_history_and_manual_evidence_survive_source_changes(self):
        self.states["alice"] = {"resume_profile": {"document_id": "new", "structured_resume": {"skills": ["Python"]}},
            "resume_versions": [{"document_id": "old", "original_file_name": "旧简历.pdf"}]}
        data = self.get()
        self.assertEqual(len(data["resumes"]), 2)
        skill = data["skills"][0]
        self.write("evidence", {"skill_id": skill["id"], "kind": "self_report", "title": "本人补充的说明"})
        self.states["alice"] = {}
        data = self.get()
        self.assertEqual(len(data["skills"]), 1)
        self.assertEqual(len(data["evidence"]), 1)
        self.assertEqual(data["evidence"][0]["source_type"], "manual")

    def test_resume_does_not_resurrect_a_deleted_manual_skill(self):
        skill = self.skill("Python")
        self.states["alice"] = {"resume_profile": {"document_id": "resume-1", "structured_resume": {"skills": ["Python"]}}}
        self.get()
        self.assertEqual(self.write("skills/" + skill["id"], {"version": 1}, "DELETE").status_code, 409)
        self.states["alice"] = {}
        self.get()
        self.assertEqual(self.write("skills/" + skill["id"], {"version": 1}, "DELETE").status_code, 200)
        self.assertEqual(self.get()["skills"], [])

    def test_assessment_import_deduplicates_server_and_browser_records(self):
        from datetime import datetime, timezone
        stamp = 1793800000000
        self.states["alice"] = {"assessment_hub": {"mbti": {"historyRuns": [{"recordedAt": stamp, "displayType": "INTJ"}]}}}
        self.get()
        payload = {"records": [{"test": "mbti", "result": "INTJ", "completed_at": datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()}]}
        self.assertEqual(self.write("assessment-import", payload).status_code, 200)
        self.assertEqual(len(self.get()["assessments"]), 1)
        payload["records"].append({"test": "sbti", "result": "探索者", "completed_at": "2026-11-04T12:00:00+08:00"})
        self.assertEqual(self.write("assessment-import", payload).status_code, 200)
        self.assertEqual(len(self.get()["assessments"]), 2)

    def test_memory_is_live_and_not_copied_to_database(self):
        self.memories = [{"id": "memory-1", "key": "skill", "subject": "Python", "value": "正在学习", "status": "active"}]
        data = self.get()
        self.assertEqual(len(data["memories"]), 1)
        self.assertEqual(data["skills"], [])
        self.memories = []
        self.assertEqual(self.get()["memories"], [])

    def test_malformed_legacy_state_does_not_break_profile(self):
        self.states["alice"] = {"resume_profile": [], "resume_versions": "legacy", "assessment_hub": {"mbti": "legacy", "holland": {"historyRuns": [None, "legacy"]}}}
        self.assertEqual(self.get()["resumes"], [])
        self.assertEqual(self.get()["assessments"], [])

    def test_account_deletion_removes_career_records_and_audit(self):
        self.skill()
        self.write("profile", {"display_name": "Alice"}, "PUT")
        db.delete_user("alice")
        for table in ("career_profiles", "career_skills", "career_revisions"):
            self.assertEqual(db._get_conn().execute(f"SELECT COUNT(*) FROM {table} WHERE owner='alice'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
