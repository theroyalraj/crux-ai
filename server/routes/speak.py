from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from server.config import get_settings
from server.tts.service import get_tts_service
from server.tts.speaker import speak_text

router = APIRouter(tags=["speak"])


class SpeakBody(BaseModel):
    text: str = Field(..., min_length=1)
    persona: str | None = None
    priority: bool = False


@router.post("/speak")
async def speak_sync(body: SpeakBody) -> dict:
    await speak_text(body.text, persona=body.persona, priority=body.priority)
    return {"ok": True, "duration_sec": 0.0}


@router.post("/speak-async")
async def speak_async(body: SpeakBody) -> JSONResponse:
    asyncio.create_task(speak_text(body.text, persona=body.persona, priority=body.priority))
    return JSONResponse({"ok": True, "accepted": True}, status_code=202)


@router.post("/tts/synthesize")
async def tts_synthesize(body: SpeakBody) -> Response:
    """MP3 bytes only; no playback on this host. Enable with CRUX_TTS_SYNTHESIZE_ENABLED."""
    s = get_settings()
    if not s.CRUX_TTS_SYNTHESIZE_ENABLED:
        raise HTTPException(status_code=503, detail="synthesize disabled")
    svc = get_tts_service()
    result = await svc.synthesize_mp3(body.text, persona=body.persona)
    if not result:
        raise HTTPException(status_code=502, detail="synthesis failed")
    data, prov = result
    return Response(
        content=data,
        media_type="audio/mpeg",
        headers={"X-Crux-Tts-Provider": prov},
    )
