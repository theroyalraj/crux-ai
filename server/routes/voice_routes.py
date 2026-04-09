from __future__ import annotations

import structlog
from fastapi import APIRouter, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from server.config import get_settings
from server.llm.router import chat
from server.voice.convai import fetch_convai_signed_url
from server.voice.hub import get_voice_hub

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])


def _voice_secret_ok(provided: str | None) -> bool:
    s = get_settings()
    expected = (s.CRUX_VOICE_WS_SECRET or "").strip()
    if not expected:
        return True
    return (provided or "").strip() == expected


class SignedUrlResponse(BaseModel):
    signed_url: str
    agent_id: str


@router.get("/convai/signed-url", response_model=SignedUrlResponse)
async def convai_signed_url(
    agent_id: str | None = Query(default=None, description="Override CRUX_ELEVENLABS_AGENT_ID"),
) -> SignedUrlResponse:
    s = get_settings()
    aid = (agent_id or "").strip() or (s.CRUX_ELEVENLABS_AGENT_ID or "").strip()
    if not aid:
        raise HTTPException(
            status_code=400,
            detail="agent_id query or CRUX_ELEVENLABS_AGENT_ID required",
        )
    url = await fetch_convai_signed_url(agent_id=aid)
    return SignedUrlResponse(signed_url=url, agent_id=aid)


@router.websocket("/ws")
async def voice_ws(
    websocket: WebSocket,
    secret: str | None = Query(default=None),
) -> None:
    if not _voice_secret_ok(secret):
        await websocket.close(code=4401)
        return
    hub = get_voice_hub()
    await hub.connect(websocket)
    try:
        while True:
            # Keep-alive; optional client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(websocket)


class ChatTurn(BaseModel):
    role: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)


class DownflowBody(BaseModel):
    transcript: str = ""
    messages: list[ChatTurn] = Field(default_factory=list)
    system: str = ""
    source: str = "voice-ui"


@router.post("/downflow")
async def voice_downflow(
    body: DownflowBody,
    x_crux_voice_secret: str | None = Header(default=None, alias="X-Crux-Voice-Secret"),
) -> dict:
    if not _voice_secret_ok(x_crux_voice_secret):
        raise HTTPException(status_code=401, detail="invalid voice secret")

    parts: list[str] = []
    if body.transcript.strip():
        parts.append(f"User speech (finalized):\n{body.transcript.strip()}")
    for m in body.messages[-40:]:
        parts.append(f"{m.role}: {m.content}")
    if not parts:
        raise HTTPException(status_code=400, detail="transcript and messages are empty")

    prompt = "\n\n".join(parts)
    return await chat(prompt, system=body.system.strip(), source=body.source)
