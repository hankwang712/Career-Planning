from copy import deepcopy
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with contextlib.redirect_stderr(io.StringIO()):
    import server

from docx import Document


def docx_bytes(text="Python developer with two years of API development and project experience."):
    stream = io.BytesIO()
    document = Document()
    document.add_paragraph(text)
    document.save(stream)
    return stream.getvalue()


class ReportUploadChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.states = {}
        self.owner = "upload-check-alice"
        self.patches = [
            patch.object(server._auth, "current_user", lambda: {"username": self.owner, "display_name": "Upload check", "role": "user"} if self.owner else None),
            patch.object(server, "_load_user_state", lambda owner: deepcopy(self.states.get(owner, {}))),
            patch.object(server, "_save_user_state", lambda owner, value: self.states.__setitem__(owner, deepcopy(value))),
            patch.object(server, "_user_upload_dir", lambda owner: str(Path(self.temp.name) / owner)),
            patch.object(server, "_find_running_resume_job", return_value=None),
            patch.object(server, "_find_running_career_report_job", return_value=None),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = server.app.test_client()

    def upload(self, filename="resume.docx", content=None):
        response = self.client.post("/api/resume/upload", data={"file": (io.BytesIO(content or docx_bytes()), filename)}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.json["data"]

    def test_upload_only_saves_file_and_does_not_parse_or_analyze(self):
        with patch.object(server, "build_resume_text_payload", side_effect=AssertionError("Upload must not parse")), patch.object(server, "_analyze_resume_matcher", side_effect=AssertionError("Upload must not analyze")):
            document = self.upload()
        self.assertFalse(document["has_resume_source_text"])
        self.assertEqual(document["status"], "uploaded")
        self.assertEqual(document["original_file_name"], "resume.docx")
        self.assertNotIn("storage_path", document)

    def test_uploaded_file_is_valid_agent_input_without_pre_reading(self):
        self.upload()
        resume = self.states[self.owner]["resume_profile"]
        inputs = server.validate_report_request({"targets": ["Python developer"]}, file_path=resume["storage_path"])
        self.assertEqual(inputs["file_path"], resume["storage_path"])
        self.assertEqual(inputs["raw_resume"], "")

    def test_existing_document_tool_reads_the_uploaded_file(self):
        from experiments.news_advisor.tools.document import read_document
        self.upload()
        path = self.states[self.owner]["resume_profile"]["storage_path"]
        document = read_document.invoke({"file_path": path, "max_pages": 20})
        self.assertEqual(document["status"], "ok")
        self.assertIn("Python developer", document["markdown"])

    def test_report_start_hands_uploaded_file_to_existing_workflow(self):
        self.upload()
        resume = self.states[self.owner]["resume_profile"]
        with patch.object(server, "_get_active_provider_and_model", return_value=("https://offline.invalid/v1", "fake-key", "offline-model")), patch.object(server, "CAREER_REPORT_JOBS", {}), patch.object(server.threading, "Thread") as thread, patch.object(server.app.extensions["chat_service"], "career_context", return_value={"preferences": "", "evidence": ""}), patch.object(server, "build_resume_text_payload", side_effect=AssertionError("Do not pre-read on the request")):
            response = self.client.post("/api/career-report/generate/start", json={"workflow": {"targets": ["Python developer"]}})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        workflow_input = thread.call_args.kwargs["args"][3]["agent_workflow"]
        self.assertEqual(workflow_input["file_path"], resume["storage_path"])
        self.assertEqual(workflow_input["raw_resume"], "")

    def test_login_required(self):
        self.owner = None
        self.assertEqual(self.client.post("/api/resume/upload").status_code, 401)

    def test_each_account_uses_its_own_upload(self):
        self.upload()
        first_path = self.states[self.owner]["resume_profile"]["storage_path"]
        self.owner = "upload-check-bob"
        self.assertFalse(self.client.get("/api/resume/profile").json["data"]["file_name"])
        self.upload()
        second_path = self.states[self.owner]["resume_profile"]["storage_path"]
        self.assertNotEqual(first_path, second_path)

    def test_replacing_same_filename_uses_unique_path(self):
        first = self.upload()
        first_path = self.states[self.owner]["resume_profile"]["storage_path"]
        second = self.upload()
        self.assertNotEqual(first["document_id"], second["document_id"])
        self.assertNotEqual(first_path, self.states[self.owner]["resume_profile"]["storage_path"])
        self.assertTrue(Path(first_path).is_file())
        self.assertEqual(self.states[self.owner]["resume_versions"][0]["document_id"], first["document_id"])

    def test_deleting_resume_removes_owned_versions_and_parsed_artifacts(self):
        self.upload()
        first = self.states[self.owner]["resume_profile"]["storage_path"]
        self.upload()
        second = self.states[self.owner]["resume_profile"]["storage_path"]
        with patch.object(server.app.extensions["chat_service"].documents, "forget") as forget:
            response = self.client.delete("/api/resume/profile")
        self.assertEqual(response.status_code, 200)
        forget.assert_called_once_with(self.owner)
        self.assertFalse(Path(first).exists())
        self.assertFalse(Path(second).exists())
        self.assertNotIn("resume_profile", self.states[self.owner])
        self.assertNotIn("resume_versions", self.states[self.owner])

    def test_running_report_blocks_replacement(self):
        document = self.upload()
        with patch.object(server, "_find_running_career_report_job", return_value={"status": "running"}):
            response = self.client.post("/api/resume/upload", data={"file": (io.BytesIO(docx_bytes()), "other.docx")}, content_type="multipart/form-data")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.states[self.owner]["resume_profile"]["document_id"], document["document_id"])



if __name__ == "__main__":
    unittest.main(verbosity=2)
