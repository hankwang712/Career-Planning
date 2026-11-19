"""统一跨域策略：Flask 与聊天 ASGI 层共用同一套来源判断与响应头。"""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from services.chat.api import ChatTransport
from services.cors import ALLOWED_HEADERS, ALLOWED_METHODS, cors_headers, normalize_origins

FRONT = "http://localhost:5173"


def test_normalize_origins_drops_blanks_and_trailing_slashes():
    assert normalize_origins([FRONT + "/", "", None, "  ", " http://a.test "]) == {FRONT, "http://a.test"}


def test_cors_headers_only_for_allowed_origins():
    headers = cors_headers(FRONT, {FRONT})
    assert headers["Access-Control-Allow-Origin"] == FRONT
    assert headers["Access-Control-Allow-Credentials"] == "true"
    assert headers["Access-Control-Allow-Methods"] == ALLOWED_METHODS
    assert headers["Access-Control-Allow-Headers"] == ALLOWED_HEADERS
    assert "X-CSRF-Token" in ALLOWED_HEADERS
    assert cors_headers("http://evil.test", {FRONT}) == {}
    assert cors_headers(None, {FRONT}) == {}
    assert cors_headers("", {FRONT}) == {}


def test_wildcard_origin_is_never_reflected():
    assert cors_headers("*", {FRONT}) == {}


def test_flask_api_adds_headers_for_configured_origin(client, monkeypatch):
    from services import webshell
    monkeypatch.setattr(webshell, "FRONTEND_ORIGIN", FRONT)
    allowed = client.get("/api/bootstrap", headers={"Origin": FRONT})
    assert allowed.headers["Access-Control-Allow-Origin"] == FRONT
    assert "Origin" in allowed.headers["Vary"]
    denied = client.get("/api/bootstrap", headers={"Origin": "http://evil.test"})
    assert "Access-Control-Allow-Origin" not in denied.headers


def test_flask_accepts_same_origin_and_ignores_non_api_paths(client):
    same = client.get("/api/bootstrap", headers={"Origin": "http://localhost"})
    assert same.headers["Access-Control-Allow-Origin"] == "http://localhost"
    page = client.get("/", headers={"Origin": FRONT})
    assert "Access-Control-Allow-Origin" not in page.headers


def test_flask_answers_api_preflight_without_cookie(client):
    response = client.options("/api/bootstrap", headers={"Origin": "http://localhost"})
    assert response.status_code == 204


def _chat_app():
    app = FastAPI()

    @app.get("/api/chat/ping")
    def ping():
        return {"ok": True}

    @app.post("/api/chat/echo")
    async def echo(request: Request):
        return {"size": len(await request.body())}

    return TestClient(ChatTransport(app, [FRONT]))


def test_chat_transport_uses_the_shared_policy():
    client = _chat_app()
    allowed = client.get("/api/chat/ping", headers={"Origin": FRONT})
    assert allowed.headers["Access-Control-Allow-Origin"] == FRONT
    assert allowed.headers["Access-Control-Allow-Methods"] == ALLOWED_METHODS
    assert allowed.headers["Cache-Control"] == "no-store"
    denied = client.get("/api/chat/ping", headers={"Origin": "http://evil.test"})
    assert "Access-Control-Allow-Origin" not in denied.headers
    assert denied.headers["Cache-Control"] == "no-store"


def test_chat_transport_allows_same_origin_and_answers_preflight():
    client = _chat_app()
    same = client.get("/api/chat/ping", headers={"Origin": "http://testserver"})
    assert same.headers["Access-Control-Allow-Origin"] == "http://testserver"
    assert client.options("/api/chat/echo", headers={"Origin": FRONT}).status_code == 204


def test_chat_transport_rejects_oversized_bodies():
    client = _chat_app()
    assert client.post("/api/chat/echo", content=b"x" * 100).json() == {"size": 100}
    assert client.post("/api/chat/echo", content=b"x" * 70000).status_code == 413
