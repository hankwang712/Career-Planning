"""简历接口：上传校验、保存、状态读取、删除，以及账号之间互不可见（不需要模型）。"""
import io
import os

from services import user_state


def pdf_file(name="cv.pdf", body=b"%PDF-1.4\n%fake resume\n"):
    return {"file": (io.BytesIO(body), name)}


def upload(account, **kwargs):
    return account.post("/api/resume/upload", data=kwargs.get("data") or pdf_file(), content_type="multipart/form-data")


def test_upload_requires_a_file(make_account):
    account = make_account("nofile")
    response = account.post("/api/resume/upload", data={}, content_type="multipart/form-data")
    assert response.status_code == 400


def test_upload_rejects_wrong_types_and_fake_pdfs(make_account):
    account = make_account("badtype")
    assert upload(account, data=pdf_file("cv.exe", b"MZ....")).status_code == 400
    assert upload(account, data=pdf_file("cv.pdf", b"not really a pdf")).status_code == 400
    assert upload(account, data=pdf_file("cv.docx", b"%PDF-1.4")).status_code == 400


def test_upload_saves_the_file_in_the_account_directory(make_account):
    account = make_account("upload")
    response = upload(account)
    assert response.status_code == 200, response.get_data(as_text=True)[:300]
    data = response.get_json()["data"]
    assert data["status"] == "uploaded" and data["original_file_name"] == "cv.pdf"
    state = user_state._load_user_state(account.email)
    path = state["resume_profile"]["storage_path"]
    assert os.path.isfile(path)
    assert user_state._owned_resume_storage_path(account.email, path) == os.path.realpath(path)


def test_profile_and_status_reflect_the_upload(make_account):
    account = make_account("status")
    assert account.get("/api/resume/profile").status_code == 200
    upload(account)
    assert account.get("/api/resume/profile").get_json()["data"]["status"] == "uploaded"
    status = account.get("/api/resume/analyze/status")
    assert status.status_code == 200 and status.get_json()["resume"]["status"] == "uploaded"


def test_replacing_a_resume_keeps_the_previous_version_in_history(make_account):
    account = make_account("replace")
    upload(account)
    first = user_state._load_user_state(account.email)["resume_profile"]["document_id"]
    upload(account, data=pdf_file("cv2.pdf"))
    state = user_state._load_user_state(account.email)
    assert state["resume_profile"]["document_id"] != first
    assert [item["document_id"] for item in state["resume_versions"]] == [first]


def test_deleting_the_resume_removes_files_and_state(make_account):
    account = make_account("delete")
    upload(account)
    path = user_state._load_user_state(account.email)["resume_profile"]["storage_path"]
    response = account.delete("/api/resume/profile")
    assert response.status_code == 200
    assert not os.path.exists(path)
    state = user_state._load_user_state(account.email)
    assert "resume_profile" not in state and "resume_versions" not in state


def test_one_account_cannot_see_or_delete_anothers_resume(make_account):
    owner, other = make_account("owner"), make_account("intruder")
    upload(owner)
    path = user_state._load_user_state(owner.email)["resume_profile"]["storage_path"]
    assert other.get("/api/resume/profile").get_json()["data"].get("document_id") in {None, ""}
    other.delete("/api/resume/profile")
    assert os.path.isfile(path)
    assert owner.get("/api/resume/profile").get_json()["data"]["status"] == "uploaded"


def test_analysis_without_a_model_reports_it(make_account):
    account = make_account("nomodel")
    upload(account)
    response = account.post("/api/resume/analyze", json={"job_description": "后端工程师"})
    assert response.status_code in {400, 503}
    assert response.get_json()["message"]
