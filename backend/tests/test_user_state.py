"""用户状态层（services/user_state.py）：账号标识、私有目录、状态读写，以及后台线程取应用引用。"""
import os
import threading

import pytest

from services import appctx, user_state


def test_login_identifiers_are_normalized():
    assert user_state._normalize_login_identifier("  Alice@Example.COM ") == "alice@example.com"
    assert user_state._normalize_login_identifier("PlainName") == "PlainName"
    assert user_state._looks_like_email("a@b.co") and not user_state._looks_like_email("not-an-email")


def test_display_name_falls_back_to_the_identifier():
    assert user_state._normalize_display_name("", "zhang.san@example.com") == "zhang san"
    assert user_state._normalize_display_name("x" * 80) == "x" * 48


def test_user_record_requires_a_username_and_defaults_the_role():
    assert user_state._normalized_user_record({"username": ""}) is None
    record = user_state._normalized_user_record({"username": "Bob@Example.com", "password_hash": " h "})
    assert record["username"] == "bob@example.com" and record["role"] == "user" and record["password_hash"] == "h"


def test_storage_key_hides_the_account_name_and_is_stable():
    key = user_state._user_storage_key("alice@example.com")
    assert key.startswith("u_") and "alice" not in key
    assert key == user_state._user_storage_key("alice@example.com")
    assert key != user_state._user_storage_key("bob@example.com")


def test_private_directories_are_per_account_and_not_guessable(server, tmp_path):
    first = user_state._private_account_directory(str(tmp_path), "alice@example.com")
    second = user_state._private_account_directory(str(tmp_path), "bob@example.com")
    assert first != second and os.path.dirname(first) == str(tmp_path)
    assert "alice" not in first


def test_user_state_round_trips_and_rejects_non_objects(make_account):
    account = make_account("state")
    assert user_state._load_user_state(account.email) == {}
    saved = user_state._save_user_state(account.email, {"career_plans": {"a": 1}})
    assert user_state._load_user_state(account.email) == saved
    assert user_state._save_user_state(account.email, ["not", "a", "dict"]) == {}
    assert user_state._load_user_state(account.email) == {}


def test_owned_resume_path_refuses_files_outside_the_account_upload_directory(make_account):
    account = make_account("owner")
    upload_dir = user_state._user_upload_dir(account.email)
    os.makedirs(upload_dir, exist_ok=True)
    inside = os.path.join(upload_dir, "resume.pdf")
    open(inside, "wb").close()
    assert user_state._owned_resume_storage_path(account.email, inside) == os.path.realpath(inside)
    assert user_state._owned_resume_storage_path(account.email, os.path.join(upload_dir, "..", "x.pdf")) == ""
    assert user_state._owned_resume_storage_path(account.email, "") == ""
    other = make_account("other")
    assert user_state._owned_resume_storage_path(other.email, inside) == ""


def test_chat_resume_source_only_exposes_an_owned_existing_file(make_account):
    account = make_account("chatresume")
    assert user_state._chat_resume_source(account.email) == {}
    upload_dir = user_state._user_upload_dir(account.email)
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, "cv.pdf")
    open(path, "wb").close()
    user_state._save_user_state(account.email, {"resume_profile": {"storage_path": path, "original_file_name": "cv.pdf",
                                                                      "document_id": "d1", "resume_source_text": "正文"}})
    source = user_state._chat_resume_source(account.email)
    assert source["name"] == "cv.pdf" and source["document_id"] == "d1" and source["text"] == "正文"
    user_state._save_user_state(account.email, {"resume_profile": {"storage_path": os.path.join(upload_dir, "gone.pdf")}})
    assert user_state._chat_resume_source(account.email) == {}


def test_background_threads_can_reach_the_app_through_appctx(server):
    seen = {}

    def work():
        seen["app"] = appctx.get_app()
        seen["service"] = appctx.get_app().extensions["chat_service"]

    thread = threading.Thread(target=work)
    thread.start()
    thread.join()
    assert seen["app"] is server.app and seen["service"] is not None


def test_appctx_complains_before_the_app_exists(monkeypatch):
    monkeypatch.setattr(appctx, "_app", None)
    with pytest.raises(RuntimeError):
        appctx.get_app()


def test_data_lock_is_reentrant():
    """保存快照等操作持锁时还会读取同一份数据；普通锁会让请求永久卡住（曾经的真实故障）。"""
    with user_state.APP_DATA_LOCK:
        with user_state.APP_DATA_LOCK:
            pass
