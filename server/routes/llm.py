from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from server.llm.router import chat

router = APIRouter(tags=["llm"])


class ChatBody(BaseModel):
    prompt: str = Field(..., min_length=1)
    system: str = ""
    source: str | None = None


@router.post("/llm/chat")
async def llm_chat(body: ChatBody) -> dict:
    return await chat(body.prompt, system=body.system, source=body.source)
