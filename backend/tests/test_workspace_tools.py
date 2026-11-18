from fastapi.testclient import TestClient

from services import db, llm_env, runtime_settings


def test_model_settings_are_private_and_reload_without_restart(make_account, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_settings, "APP_DATA_DIR", tmp_path)
    monkeypatch.setenv("AI_CHAT_MODEL", "deployment-model")
    admin = make_account("model-admin")
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET role = 'super_admin' WHERE username = ?", (admin.email,))
    user = make_account("model-user")
    endpoint = "/api/system-settings/models"
    changes = {
        "AI_CHAT_BASE_URL": "https://provider.example/v1",
        "AI_CHAT_API_KEY": "test-secret",
        "AI_CHAT_MODEL": "web-model",
    }

    assert user.get(endpoint).status_code == 403
    assert user.request("patch", endpoint, json=changes).status_code == 403
    assert admin.client.patch(endpoint, json=changes).status_code == 403
    assert admin.get("/system-settings").status_code == 200
    assert "/system-settings" in admin.get("/").get_data(as_text=True)
    assert admin.request("patch", endpoint, json={**changes, "POSTGRES_PASSWORD": "test"}).status_code == 400
    assert admin.request("patch", endpoint, json={"AI_CHAT_BASE_URL": "https://example.test/?api_key=secret"}).status_code == 400

    saved = admin.request("patch", endpoint, json=changes)
    assert saved.status_code == 200
    assert "test-secret" not in saved.get_data(as_text=True)
    assert saved.get_json()["fields"]["AI_CHAT_API_KEY"] == {"configured": True, "override": True}
    assert llm_env.chat_runtime() == ("https://provider.example/v1", "test-secret", "web-model")
    assert user.get("/api/llm-status").get_json() == {"configured": True, "model": "web-model"}
    assert admin.request("patch", endpoint, json={"AI_CHAT_MODEL": ""}).status_code == 200
    assert llm_env.chat_runtime()[2] == "deployment-model"


def test_request_console_is_scoped_and_omits_request_data(server, make_account):
    first = make_account("log-first")
    second = make_account("log-second")
    assert server.app.test_client().get("/api/workspace-logs").status_code == 401
    first.get("/api/llm-status?private=secret-query")
    asgi = TestClient(server.asgi_app)
    session = first.client.get_cookie(server.app.config["SESSION_COOKIE_NAME"])
    assert asgi.get("/api/chat/sessions", headers={"Cookie": f"{session.key}={session.value}"}).status_code == 200
    response = first.get("/api/workspace-logs")
    assert "no-store" in response.headers["Cache-Control"]
    assert "secret-query" not in response.get_data(as_text=True)
    paths = {entry["route"] for entry in response.get_json()["entries"]}
    assert {"/api/llm-status", "/api/chat/sessions"} <= paths
    assert "/api/workspace-logs" not in paths
    paths = {entry["route"] for entry in second.get("/api/workspace-logs").get_json()["entries"]}
    assert "/api/llm-status" not in paths
    assert "/api/chat/sessions" not in paths
