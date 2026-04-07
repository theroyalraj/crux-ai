from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
