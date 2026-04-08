from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ActionItem(BaseModel):
    priority: Literal["HIGH", "MEDIUM", "LOW"]
    subject: str
    from_email: str = ""
    action: str = ""


class DispatchPayload(BaseModel):
    generated_at: str
    char_count: int = 0
    total_items: int
    high_priority_count: int
    medium_priority_count: int
    low_priority_count: int
    whatsapp_message: str = ""
    items: list[ActionItem] = Field(default_factory=list)


class MarkDoneRequest(BaseModel):
    numbers: list[int]


class ActionStatusItem(BaseModel):
    number: int
    priority: str
    subject: str
    status: str
    done_at: datetime | None = None


class DeltaResponse(BaseModel):
    has_new_items: bool
    has_high: bool
    has_medium: bool
    new_items: list[ActionStatusItem]
    next_number: int
