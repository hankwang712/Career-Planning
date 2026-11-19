import sqlite3

import pytest

from services import auth


def workspace_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE users (username TEXT PRIMARY KEY, password_hash TEXT, role TEXT, display_name TEXT,
                            disabled INTEGER DEFAULT 0, last_login_at REAL, created_at REAL DEFAULT 0);
        CREATE TABLE auth_settings (name TEXT PRIMARY KEY, value TEXT);
    """)
    return conn


def test_new_workspace_starts_without_accounts():
    with workspace_db() as conn:
        assert auth.select_workspace(conn)["username"] == "local-workspace"
        assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 1
        assert auth.select_workspace(conn)["username"] == "local-workspace"


def test_existing_workspace_keeps_its_storage_key():
    with workspace_db() as conn:
        conn.executemany("""
            INSERT INTO users (username, role, disabled, last_login_at) VALUES (?, ?, ?, ?)
        """, [("old@example.com", "super_admin", 0, 3), ("latest@example.com", "user", 0, 4),
              ("disabled@example.com", "super_admin", 1, 5)])
        assert auth.select_workspace(conn)["username"] == "latest@example.com"
        conn.execute("UPDATE users SET last_login_at = 6 WHERE username = 'old@example.com'")
        assert auth.select_workspace(conn)["username"] == "latest@example.com"


def test_workspace_is_shared_across_cookie_free_clients(server):
    first, second = server.app.test_client(), server.app.test_client()
    response = first.put("/api/user-state/news_context", json={"data": {"local_test": True}})
    assert response.status_code == 200
    try:
        assert second.get("/api/user-state/news_context").get_json()["data"] == {"local_test": True}
        assert first.get("/api/bootstrap").get_json()["user"] == second.get("/api/bootstrap").get_json()["user"]
    finally:
        first.put("/api/user-state/news_context", json={"data": None})


@pytest.mark.parametrize("path", ["login", "register", "logout", "password", "challenge", "status"])
def test_old_auth_endpoints_are_removed(client, path):
    assert client.get("/api/auth/" + path).status_code == 404
    assert client.post("/api/auth/" + path).status_code == 404


@pytest.mark.parametrize("headers,env", [
    ({"Host": "example.test"}, {}),
    ({"Origin": "http://example.test"}, {}),
    ({"X-Forwarded-For": "127.0.0.1"}, {"REMOTE_ADDR": "192.0.2.10"}),
])
def test_workspace_rejects_nonlocal_requests(client, headers, env):
    assert client.get("/api/bootstrap", headers=headers, environ_overrides=env).status_code == 403


def test_workspace_csrf_is_independent_of_login(client):
    route = "/api/resume-editor/rewrite/settings"
    assert client.post(route, json={}).status_code == 403
    token = client.get("/api/workspace/security").get_json()["csrf_token"]
    assert client.post(route, headers={"X-CSRF-Token": token}, json={}).status_code == 400
