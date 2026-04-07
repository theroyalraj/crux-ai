from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server.config import get_settings
from server.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def voice_client(monkeypatch):
    monkeypatch.setenv("CRUX_VOICE_WS_SECRET", "")
    monkeypatch.setenv("CRUX_CORS_ORIGINS", "")
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_voice_downflow_empty_400(voice_client):
    r = await voice_client.post("/voice/downflow", json={"transcript": "", "messages": []})
    assert r.status_code == 400


@pytest.mark.anyio
async def test_voice_downflow_calls_chat(voice_client, monkeypatch):
    async def fake_chat(prompt: str, system: str = "", source: str | None = None, **kw):
        return {"response": f"echo:{prompt[:20]}", "cached": False}

    monkeypatch.setattr("server.routes.voice_routes.chat", fake_chat)
    r = await voice_client.post(
        "/voice/downflow",
        json={"transcript": "hello world", "messages": [], "source": "t"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "echo:" in data.get("response", "")


def test_voice_ws_connect(monkeypatch):
    monkeypatch.setenv("CRUX_VOICE_WS_SECRET", "")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/voice/ws") as ws:
                ws.send_text("ping")
    finally:
        get_settings.cache_clear()


def test_voice_ws_secret_rejects(monkeypatch):
    monkeypatch.setenv("CRUX_VOICE_WS_SECRET", "s3cret")
    get_settings.cache_clear()
    try:
        with TestClient(app) as client:
            with pytest.raises(WebSocketDisconnect) as ei:
                with client.websocket_connect("/voice/ws"):
                    pass
            assert ei.value.code == 4401
    finally:
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_convai_signed_url_requires_agent(monkeypatch):
    monkeypatch.setenv("CRUX_ELEVENLABS_AGENT_ID", "")
    get_settings.cache_clear()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/voice/convai/signed-url")
            assert r.status_code == 400
    finally:
        get_settings.cache_clear()
