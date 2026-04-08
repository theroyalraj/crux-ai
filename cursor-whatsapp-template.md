# Twilio WhatsApp Template — Daily Action Plan

---

## PART 1 — Twilio Console Steps

### Step 1 — Open Content Template Builder
1. Log in → https://console.twilio.com
2. Left sidebar: **Messaging → Content Template Builder**
3. Click **Create new template**

### Step 2 — Choose these options exactly
| Field | Choose |
|---|---|
| **Template name** | `daily_action_plan` |
| **Category** | `UTILITY` |
| **Language** | `English (en)` |
| **Content type** | `Text` |

> ⚠️ Do NOT choose Marketing — utility templates get approved faster and avoid spam filters.

### Step 3 — Paste this as the Body (171 chars — well within 1024 limit)

```
📋 *Action Plan* — {{1}}
*{{2}} items:* 🔴{{3}} High • 🟡{{4}} Medium • 🟢{{5}} Low
━━━━━━━━━━━━━━━
🔴 *HIGH*
{{6}}
━━━━━━━━━━━━━━━
🟡 _{{7}}_
🟢 _{{8}}_
━━━━━━━━━━━━━━━
🤖 _Claude · 10 AM IST_
```

### Step 4 — Fill Sample Values (required for WhatsApp approval)
Twilio shows these to WhatsApp reviewers. Use realistic examples:

| Variable | Sample Value |
|---|---|
| `{{1}}` | `Thu, Apr 9` |
| `{{2}}` | `9` |
| `{{3}}` | `3` |
| `{{4}}` | `4` |
| `{{5}}` | `2` |
| `{{6}}` | `1. Performance review closes TODAY 3PM\n   👉 Complete actions\n\n2. MR !105 review pending\n   👉 Respond to Chaitanya` |
| `{{7}}` | `4 items: meetings, code reviews, MR merges` |
| `{{8}}` | `2 items: commission OK ✅, notifications` |

### Step 5 — Submit
1. Click **Save and submit**
2. Status will show **Pending** → changes to **Approved** within minutes (ML-based review)
3. Once approved, copy the **Content SID** → it starts with `HX...`
4. Paste it in `.env` as `WHATSAPP_CONTENT_SID=HXxxxxxxx`

---

## PART 2 — What Each Variable Contains

| Variable | Content | Example |
|---|---|---|
| `{{1}}` | Day + date | `Thu, Apr 9` |
| `{{2}}` | Total item count | `9` |
| `{{3}}` | High priority count | `3` |
| `{{4}}` | Medium priority count | `4` |
| `{{5}}` | Low priority count | `2` |
| `{{6}}` | HIGH items — numbered, with action | `1. Subject\n   👉 Action\n\n2. Subject\n   👉 Action` |
| `{{7}}` | MEDIUM summary — one-liner | `4 items: meetings, code reviews, pending MRs` |
| `{{8}}` | LOW summary — one-liner | `2 items: commission OK ✅, routine notifications` |

---

## PART 3 — Cursor Prompt (paste this into Cursor)

```
Update the WhatsApp dispatch route in D:\code\crux-ai to:
1. Build content_variables JSON for the approved Twilio Content Template
2. Send via Content SID when WHATSAPP_CONTENT_SID is set, free-form sandbox otherwise

The server is FastAPI at 127.0.0.1:9090. Follow the style of server/routes/speak.py exactly.

---

## Config — server/config.py

Inside CruxSettings, add:

    # WhatsApp (Twilio)
    WHATSAPP_ENABLED: bool = False
    WHATSAPP_ACCOUNT_SID: str = ""
    WHATSAPP_AUTH_TOKEN: str = ""
    WHATSAPP_FROM: str = "whatsapp:+14155238886"
    WHATSAPP_TO: str = ""
    WHATSAPP_CONTENT_SID: str = ""   # HX... from Twilio Content Template Builder

---

## Route — server/routes/whatsapp.py

from __future__ import annotations

import json
import re
from datetime import datetime

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
    whatsapp_message: str         # fallback free-form message (sandbox)
    items: list[dict] = []


def _format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%a, %b %-d")
    except Exception:
        return re.sub(r"T.*", "", iso)


def _build_high_items(items: list[dict]) -> str:
    high = [it for it in items if it.get("priority") == "HIGH"]
    if not high:
        return "None today ✅"
    lines = []
    for i, it in enumerate(high, 1):
        subject = it.get("subject", "")
        action = it.get("action", "")
        lines.append(f"{i}. {subject}\n   👉 {action}")
    return "\n\n".join(lines)


def _build_medium_summary(items: list[dict]) -> str:
    medium = [it for it in items if it.get("priority") == "MEDIUM"]
    if not medium:
        return "None today ✅"
    subjects = ", ".join(it.get("subject", "") for it in medium[:3])
    suffix = f" +{len(medium)-3} more" if len(medium) > 3 else ""
    return f"{len(medium)} items: {subjects}{suffix}"


def _build_low_summary(items: list[dict]) -> str:
    low = [it for it in items if it.get("priority") == "LOW"]
    if not low:
        return "None today ✅"
    subjects = ", ".join(it.get("subject", "") for it in low[:2])
    suffix = f" +{len(low)-2} more" if len(low) > 2 else ""
    return f"{len(low)} items: {subjects}{suffix}"


@router.post("/whatsapp/dispatch")
async def whatsapp_dispatch(payload: DispatchPayload) -> dict:
    """
    Send daily action plan via WhatsApp (Twilio).

    - WHATSAPP_CONTENT_SID set  → uses approved Content Template (production)
    - WHATSAPP_CONTENT_SID empty → sends free-form message (sandbox, no approval needed)
    """
    s = get_settings()

    if not s.WHATSAPP_ENABLED:
        log.info("whatsapp_skipped", reason="disabled")
        return {"ok": True, "skipped": True}

    for field, val in [
        ("WHATSAPP_ACCOUNT_SID", s.WHATSAPP_ACCOUNT_SID),
        ("WHATSAPP_AUTH_TOKEN", s.WHATSAPP_AUTH_TOKEN),
        ("WHATSAPP_TO", s.WHATSAPP_TO),
    ]:
        if not val:
            raise HTTPException(status_code=503, detail=f"{field} not set in .env")

    try:
        from twilio.rest import Client
        client = Client(s.WHATSAPP_ACCOUNT_SID, s.WHATSAPP_AUTH_TOKEN)

        if s.WHATSAPP_CONTENT_SID:
            # Production: approved template with variables
            content_variables = json.dumps({
                "1": _format_date(payload.generated_at),
                "2": str(payload.total_items),
                "3": str(payload.high_priority_count),
                "4": str(payload.medium_priority_count),
                "5": str(payload.low_priority_count),
                "6": _build_high_items(payload.items),
                "7": _build_medium_summary(payload.items),
                "8": _build_low_summary(payload.items),
            })
            msg = client.messages.create(
                content_sid=s.WHATSAPP_CONTENT_SID,
                content_variables=content_variables,
                from_=s.WHATSAPP_FROM,
                to=s.WHATSAPP_TO,
            )
            mode = "template"
        else:
            # Sandbox: free-form (no approval needed, join code required)
            msg = client.messages.create(
                body=payload.whatsapp_message,
                from_=s.WHATSAPP_FROM,
                to=s.WHATSAPP_TO,
            )
            mode = "sandbox"

        log.info("whatsapp_sent", sid=msg.sid, mode=mode, total=payload.total_items)
        return {"ok": True, "sid": msg.sid, "mode": mode, "total_items": payload.total_items}

    except Exception as exc:
        log.error("whatsapp_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/whatsapp/status")
async def whatsapp_status() -> dict:
    s = get_settings()
    return {
        "enabled": s.WHATSAPP_ENABLED,
        "mode": "template" if s.WHATSAPP_CONTENT_SID else "sandbox",
        "from": s.WHATSAPP_FROM,
        "to_set": bool(s.WHATSAPP_TO),
        "credentials_set": bool(s.WHATSAPP_ACCOUNT_SID and s.WHATSAPP_AUTH_TOKEN),
    }

---

## main.py changes

Add to imports:
  from server.routes import git_routes, health, internal, llm, speak, whatsapp

Add after existing routers:
  app.include_router(whatsapp.router)

---

## .env additions

WHATSAPP_ENABLED=true
WHATSAPP_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WHATSAPP_AUTH_TOKEN=your_auth_token
WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
WHATSAPP_CONTENT_SID=    # leave empty for sandbox; add HX... after template approved

---

## requirements.txt

Add:
  twilio>=9.0.0

---

## Test (sandbox — no template needed)

curl http://127.0.0.1:9090/whatsapp/status

curl -X POST http://127.0.0.1:9090/whatsapp/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "generated_at": "2026-04-09T10:00:00+05:30",
    "total_items": 6,
    "high_priority_count": 2,
    "medium_priority_count": 3,
    "low_priority_count": 1,
    "whatsapp_message": "📋 *Action Plan* — Thu, Apr 9\n*6 items:* 🔴2 High • 🟡3 Medium • 🟢1 Low\n━━━━━━━━━━━━━━━\n🔴 *HIGH*\n1. Performance Review closes 3PM\n   👉 Complete actions\n\n2. MR !105 code review\n   👉 Respond to comment\n━━━━━━━━━━━━━━━\n🟡 _3 items: meetings, code reviews, MR merge_\n🟢 _1 item: commission OK ✅_\n━━━━━━━━━━━━━━━\n🤖 _Claude · 10 AM IST_",
    "items": [
      {"priority": "HIGH", "subject": "Performance Review closes 3PM", "action": "Complete actions"},
      {"priority": "HIGH", "subject": "MR !105 code review", "action": "Respond to comment"},
      {"priority": "MEDIUM", "subject": "Inventory Out RCA Meeting", "action": "Join call at 2:30PM"},
      {"priority": "MEDIUM", "subject": "MR !106 Bito review", "action": "Review findings"},
      {"priority": "MEDIUM", "subject": "MR !405 tradeType", "action": "Final review and merge"},
      {"priority": "LOW", "subject": "Commission processing OK", "action": "No action"}
    ]
  }'
```

---

## What the WhatsApp message looks like (Production template)

📋 *Action Plan* — Thu, Apr 9
*6 items:* 🔴2 High • 🟡3 Medium • 🟢1 Low
━━━━━━━━━━━━━━━
🔴 *HIGH*
1. Performance Review closes 3PM
   👉 Complete actions

2. MR !105 code review
   👉 Respond to comment
━━━━━━━━━━━━━━━
🟡 _3 items: meetings, code reviews, MR merge_
🟢 _1 item: commission OK ✅_
━━━━━━━━━━━━━━━
🤖 _Claude · 10 AM IST_
