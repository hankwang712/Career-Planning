"""认证：注册、登录、CSRF、会话失效与限流。"""
import time

import pytest

from conftest import issue_captcha, reset_rate_limits
from services import auth, db


def login(server, client, email, password, *, captcha=True):
    reset_rate_limits()
    csrf, answer = issue_captcha(server, client, "login")
    body = {"username": email, "password": password}
    if captcha:
        body.update(answer)
    return client.post("/api/auth/login", headers={"X-CSRF-Token": csrf}, json=body)


def test_register_starts_a_session(make_account):
    account = make_account("alice")
    status = account.get("/api/auth/status").get_json()
    assert status["authenticated"] is True
    assert status["user"]["username"] == account.email
    assert status["user"]["role"] == "user"
    assert status["user"]["can_manage_configs"] is False


def test_status_never_exposes_password_hash(make_account):
    account = make_account()
    assert "password" not in account.get("/api/auth/status").get_data(as_text=True).lower()


def test_duplicate_registration_is_rejected_without_revealing_details(server, make_account):
    first = make_account("dup")
    client = server.app.test_client()
    csrf, captcha = issue_captcha(server, client, "register")
    response = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf}, json={
        "email": first.email, "password": "another-password", "confirm_password": "another-password", **captcha})
    assert response.status_code == 409


def test_register_validates_input(server):
    reset_rate_limits()
    client = server.app.test_client()
    csrf, captcha = issue_captcha(server, client, "register")
    mismatch = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf}, json={
        "email": "mismatch@example.com", "password": "abcdef123", "confirm_password": "different", **captcha})
    assert mismatch.status_code == 400
    csrf, captcha = issue_captcha(server, client, "register")
    bad_email = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf}, json={
        "email": "not-an-email", "password": "abcdef123", "confirm_password": "abcdef123", **captcha})
    assert bad_email.status_code == 400


def test_register_requires_a_valid_captcha(server):
    client = server.app.test_client()
    csrf = client.get("/api/auth/security").get_json()["csrf_token"]
    response = client.post("/api/auth/register", headers={"X-CSRF-Token": csrf}, json={
        "email": "nocaptcha@example.com", "password": "abcdef123", "confirm_password": "abcdef123",
        "captcha_id": "missing", "captcha_answer": "ZZZZZ"})
    assert response.status_code == 400
    assert "验证码" in response.get_json()["message"]


def test_captcha_is_single_use(server):
    client = server.app.test_client()
    csrf, captcha = issue_captcha(server, client, "login")
    body = {"username": "ghost@example.com", "password": "whatever", **captcha}
    first = client.post("/api/auth/login", headers={"X-CSRF-Token": csrf}, json=body)
    second = client.post("/api/auth/login", headers={"X-CSRF-Token": csrf}, json=body)
    assert first.status_code == 401  # 验证码通过，账号不存在
    assert second.status_code == 400  # 同一个验证码不能再用


def test_login_with_correct_and_wrong_password(server, make_account):
    account = make_account("bob")
    fresh = server.app.test_client()
    wrong = login(server, fresh, account.email, "not-the-password")
    assert wrong.status_code == 401
    right = login(server, fresh, account.email, account.password)
    assert right.status_code == 200
    assert right.get_json()["user"]["username"] == account.email


def test_login_error_is_identical_for_unknown_account_and_wrong_password(server, make_account):
    account = make_account("carol")
    wrong = login(server, server.app.test_client(), account.email, "bad-password-1")
    unknown = login(server, server.app.test_client(), "nobody-here@example.com", "bad-password-1")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json()["message"] == unknown.get_json()["message"]


def test_login_requires_captcha(server, make_account):
    account = make_account("dave")
    response = login(server, server.app.test_client(), account.email, account.password, captcha=False)
    assert response.status_code == 400


def test_state_changing_auth_calls_need_a_csrf_token(server):
    client = server.app.test_client()
    client.get("/api/auth/security")
    assert client.post("/api/auth/logout").status_code == 403
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403


def test_logout_ends_the_session(make_account):
    account = make_account("erin")
    assert account.get("/api/llm-status").status_code == 200
    assert account.post("/api/auth/logout").status_code == 200
    assert account.get("/api/llm-status").status_code == 401
    assert account.get("/api/auth/status").get_json()["authenticated"] is False


def test_password_change_revokes_other_sessions(server, make_account):
    account = make_account("frank")
    other = server.app.test_client()
    assert login(server, other, account.email, account.password).status_code == 200
    assert other.get("/api/llm-status").status_code == 200

    changed = account.put("/api/auth/password", json={
        "current_password": account.password, "new_password": "brand-new-password", "confirm_password": "brand-new-password"})
    assert changed.status_code == 200
    assert other.get("/api/llm-status").status_code == 401
    assert account.get("/api/llm-status").status_code == 200  # 当前设备保持登录

    assert login(server, server.app.test_client(), account.email, account.password).status_code == 401
    assert login(server, server.app.test_client(), account.email, "brand-new-password").status_code == 200


def test_password_change_checks_current_password(make_account):
    account = make_account("gina")
    response = account.put("/api/auth/password", json={
        "current_password": "wrong", "new_password": "brand-new-password", "confirm_password": "brand-new-password"})
    assert response.status_code == 400


def test_disabled_accounts_cannot_log_in_or_keep_sessions(server, make_account):
    account = make_account("harry")
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET disabled = 1 WHERE username = ?", (account.email,))
    assert account.get("/api/llm-status").status_code == 401
    assert login(server, server.app.test_client(), account.email, account.password).status_code == 401


def test_expired_sessions_are_not_accepted(make_account):
    account = make_account("ivy")
    with db._get_conn() as conn:
        conn.execute("UPDATE auth_sessions SET expires_at = ? WHERE username = ?", (time.time() - 5, account.email))
    assert account.get("/api/llm-status").status_code == 401


def test_rate_limit_blocks_after_the_limit_and_reports_retry_after(server):
    with server.app.test_request_context("/"):
        for _ in range(3):
            auth.rate_limit("unit-test", "client-1", 3, 600)
        with pytest.raises(auth.AuthError) as error:
            auth.rate_limit("unit-test", "client-1", 3, 600)
        assert error.value.status == 429
        assert error.value.retry_after >= 1
        # 不同标识互不影响
        auth.rate_limit("unit-test", "client-2", 3, 600)


@pytest.mark.parametrize("raw,expected", [
    ("User@Example.COM", "user@example.com"),
])
def test_email_is_normalized_to_lowercase(raw, expected):
    assert auth.normalize_email(raw) == expected


@pytest.mark.parametrize("raw", ["", " a@b.co", "a@b", "a b@c.com", "x" * 300 + "@example.com", None, 123])
def test_invalid_emails_are_rejected(raw):
    with pytest.raises(auth.AuthError):
        auth.normalize_email(raw)
