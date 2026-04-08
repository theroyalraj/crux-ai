# Cursor Prompt — Add WhatsApp Dispatch Route to crux-ai

## Context
This is a FastAPI server (`server/main.py`) running on `127.0.0.1:9090`.
Routes follow the pattern in `server/routes/speak.py`.
Config is in `server/config.py` using `pydantic-settings` with `.env`.

A scheduled Claude task will POST to `POST /whatsapp/dispatch` every morning at 10 AM IST
with a JSON payload containing a daily email action plan summary, and you need to forward it
to WhatsApp via Twilio.

## Task
Implement the `POST /whatsapp/dispatch` endpoint following the existing code conventions exactly.

---

## 1. Add dependencies to `requirements.txt`
Add:
```
twilio>=9.0.0
```

---

## 2. Add WhatsApp config fields to `server/config.py`

Inside the `CruxSettings` class, add a new section at the bottom (before the `@functools.lru_cache` line):

```python
# WhatsApp (Twilio)
WHATSAPP_ENABLED: bool = False
WHATSAPP_ACCOUNT_SID: str = ""
WHATSAPP_AUTH_TOKEN: str = ""
WHATSAPP_FROM: str = "whatsapp:+14155238886"   # Twilio sandbox default
WHATSAPP_TO: str = ""                            # e.g. whatsapp:+919999999999
```

---

## 3. Create `server/routes/whatsapp.py`

Follow the exact same style as `server/routes/speak.py`:

```python
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.config import get_settings

router = APIRouter(tags=["whatsapp"])
log = structlog.get_logger(__name__)


class DispatchPayload(BaseModel):
    generated_at: str
    total_items: int
    high_priority_count: int
    medium_priority_count: int
    low_priority_count: int
    whatsapp_message: str
    items: list[dict] = []


@router.post("/whatsapp/dispatch")
async def whatsapp_dispatch(payload: DispatchPayload) -> dict:
    """Receive a daily action plan payload and send it via WhatsApp (Twilio)."""
    s = get_settings()

    if not s.WHATSAPP_ENABLED:
        log.info("whatsapp_dispatch_skipped", reason="WHATSAPP_ENABLED=false")
        return {"ok": True, "skipped": True, "reason": "WHATSAPP_ENABLED is false"}

    if not s.WHATSAPP_ACCOUNT_SID or not s.WHATSAPP_AUTH_TOKEN:
        raise HTTPException(status_code=503, detail="Twilio credentials not configured")

    if not s.WHATSAPP_TO:
        raise HTTPException(status_code=503, detail="WHATSAPP_TO not configured")

    try:
        from twilio.rest import Client  # lazy import — only needed when enabled

        client = Client(s.WHATSAPP_ACCOUNT_SID, s.WHATSAPP_AUTH_TOKEN)
        message = client.messages.create(
            body=payload.whatsapp_message,
            from_=s.WHATSAPP_FROM,
            to=s.WHATSAPP_TO,
        )
        log.info(
            "whatsapp_sent",
            sid=message.sid,
            total_items=payload.total_items,
            high=payload.high_priority_count,
        )
        return {"ok": True, "sid": message.sid, "total_items": payload.total_items}

    except Exception as exc:
        log.error("whatsapp_dispatch_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {exc}") from exc
```

---

## 4. Register the router in `server/main.py`

Add the import alongside the other route imports:
```python
from server.routes import git_routes, health, internal, llm, speak, whatsapp
```

Add the router registration after the existing ones:
```python
app.include_router(whatsapp.router)
```

---

## 5. Add env vars to `.env` (and `.env.example`)

```env
# WhatsApp (Twilio) — get credentials from console.twilio.com
WHATSAPP_ENABLED=true
WHATSAPP_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WHATSAPP_AUTH_TOKEN=your_auth_token_here
WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
```

**Twilio setup steps:**
1. Sign up at https://console.twilio.com
2. Go to Messaging → Try it out → Send a WhatsApp message
3. Join the sandbox by sending "join <your-sandbox-word>" to the Twilio number from your WhatsApp
4. Copy Account SID and Auth Token from the dashboard
5. Set `WHATSAPP_FROM` to `whatsapp:+14155238886` (sandbox) or your approved number
6. Set `WHATSAPP_TO` to `whatsapp:+91XXXXXXXXXX` (your number with country code)

---

## 6. Install the dependency and restart

```bash
pip install twilio
# then restart the server
```

---

## Test the endpoint manually

```bash
curl -X POST http://127.0.0.1:9090/whatsapp/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "generated_at": "2026-04-09T10:00:00+05:30",
    "total_items": 3,
    "high_priority_count": 1,
    "medium_priority_count": 1,
    "low_priority_count": 1,
    "whatsapp_message": "📋 *Daily Action Plan* — Apr 9\n\n🔴 HIGH\n1. Test item — test@test.com | Reply now\n\n🟡 MEDIUM\n1. Review PR\n\n🟢 LOW\n1. Newsletter",
    "items": []
  }'
```

Expected response: `{"ok": true, "sid": "SMxxxxxxx", "total_items": 3}`
