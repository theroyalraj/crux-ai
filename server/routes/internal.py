from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from server.config import get_settings
from server.daemons.committer import get_hourly_decision_box

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_internal_secret(
    x_crux_secret: str | None = Header(default=None, alias="X-Crux-Secret"),
) -> bool:
    s = get_settings()
    secret = (s.CRUX_INTERNAL_SECRET or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="internal routes disabled")
    if (x_crux_secret or "").strip() != secret:
        raise HTTPException(status_code=403, detail="forbidden")
    return True


class HourlyDecisionBody(BaseModel):
    decision: str = Field(..., description="yes or no")


@router.post("/hourly-decision")
async def hourly_decision(
    body: HourlyDecisionBody,
    _: bool = Depends(verify_internal_secret),
) -> dict:
    box = get_hourly_decision_box()
    if box is None:
        raise HTTPException(status_code=503, detail="committer not running")
    box.submit(body.decision)
    return {"ok": True}
