from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

from services import db, llm_env, runtime_settings, workspace_tools


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
    assert user.get("/system-settings").status_code == 200
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
    reveal = "/api/system-settings/reveal"
    assert user.post(reveal, json={"key": "AI_CHAT_API_KEY"}).status_code == 403
    assert admin.client.post(reveal, json={"key": "AI_CHAT_API_KEY"}).status_code == 403
    assert admin.post(reveal, json={"key": "POSTGRES_PASSWORD"}).status_code == 400
    revealed = admin.post(reveal, json={"key": "AI_CHAT_API_KEY"})
    assert revealed.get_json() == {"value": "test-secret"}
    assert "no-store" in revealed.headers["Cache-Control"]
    assert "test-secret" not in admin.get("/api/system-settings/status").get_data(as_text=True)
    assert llm_env.chat_runtime() == ("https://provider.example/v1", "test-secret", "web-model")
    assert user.get("/api/llm-status").get_json() == {"configured": True, "model": "web-model"}
    overview = user.get("/api/system-settings/status").get_json()["fields"]
    assert "POSTGRES_PASSWORD" in overview
    assert overview["AI_CHAT_BASE_URL"]["configured"]
    assert all("value" not in field for field in overview.values())
    assert admin.request("patch", endpoint, json={"AI_CHAT_MODEL": ""}).status_code == 200
    assert llm_env.chat_runtime()[2] == "deployment-model"

    cleaner = {
        "CLEANER_LLM_BASE_URL": "https://clean.example/v1", "CLEANER_LLM_API_KEY": "cleaner-secret",
        "CLEANER_LLM_MODEL": "clean-text", "CLEANER_VISION_MODEL": "clean-vision",
    }
    assert "招聘清洗模型" in admin.get("/system-settings").get_data(as_text=True)
    assert user.request("patch", endpoint, json=cleaner).status_code == 403
    updated = admin.request("patch", endpoint, json=cleaner)
    assert updated.status_code == 200 and "cleaner-secret" not in updated.get_data(as_text=True)
    assert llm_env.recruitment_cleaner_runtime()[2] == "clean-text"
    assert llm_env.recruitment_cleaner_runtime(vision=True)[2] == "clean-vision"
    assert admin.request("patch", endpoint, json={"USE_MAIN_LLM_FOR_CLEANER": "true"}).status_code == 200
    assert llm_env.recruitment_cleaner_runtime() == llm_env.chat_runtime()
    assert llm_env.recruitment_cleaner_runtime(vision=True)[2] == "clean-vision"


def test_connection_probes_the_saved_model_without_returning_provider_payload(make_account, monkeypatch):
    admin = make_account("probe-admin")
    user = make_account("probe-user")
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET role = 'super_admin' WHERE username = ?", (admin.email,))
    endpoint = "/api/system-settings/test/chat"
    monkeypatch.setattr(llm_env, "chat_runtime", lambda: ("https://provider.example", "probe-secret", "saved-model"))
    requests = []
    status = 200

    def provider(request):
        requests.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": "provider-private-details"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}]})

    net = SimpleNamespace(Client=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(provider), **kwargs),
                          HTTPError=httpx.HTTPError)
    monkeypatch.setattr(workspace_tools, "httpx", net)
    assert user.post(endpoint).status_code == 403
    assert admin.client.post(endpoint).status_code == 403
    response = admin.post(endpoint, json={"base_url": "https://ignored.example"})
    assert response.status_code == 200
    assert requests[0].url == "https://provider.example/v1/chat/completions"
    assert b'"model":"saved-model"' in requests[0].content
    assert "probe-secret" not in response.get_data(as_text=True)

    status = 401
    response = admin.post(endpoint)
    assert response.status_code == 502
    assert "401" in response.get_json()["message"]
    assert "provider-private-details" not in response.get_data(as_text=True)


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
