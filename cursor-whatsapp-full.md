# WhatsApp Daily Action Plan — Full Setup Guide + Cursor Prompt

---

## PART 1 — Twilio Console Setup (Do This First)

### Step 1 — Create Account
1. Go to https://console.twilio.com → Sign up (free)
2. Verify your phone number (this will be your WhatsApp recipient number)

### Step 2 — Activate WhatsApp Sandbox (for immediate testing)
1. In the left sidebar: **Messaging → Try it out → Send a WhatsApp message**
2. You'll see a number like `+1 415 523 8886` and a join code like `join silver-tiger`
3. Open WhatsApp on your phone → send that exact message to that number
4. You'll get a reply confirming you're in the sandbox ✅
5. Copy your **Account SID** and **Auth Token** from the main dashboard

> Sandbox is free, instant, no template approval needed.
> Limitation: Only numbers who sent the join code can receive messages.

### Step 3 — Get your credentials
From https://console.twilio.com (main page):
- `WHATSAPP_ACCOUNT_SID` = Account SID (starts with `AC...`)
- `WHATSAPP_AUTH_TOKEN` = Auth Token (click the eye icon to reveal)
- `WHATSAPP_FROM` = `whatsapp:+14155238886` (Twilio sandbox number)
- `WHATSAPP_TO` = `whatsapp:+91XXXXXXXXXX` (your number with country code)

### Step 4 — Create a Content Template (for Production — do after sandbox works)
1. Go to **Messaging → Content Template Builder → Create new template**
2. Choose options:
   - **Category**: `UTILITY` (daily notifications, not marketing)
   - **Language**: `English (en)`
   - **Template name**: `daily_action_plan` (lowercase, underscores only)
   - **Template type**: `Text` (plain text message, no buttons needed)
3. Paste this as the **Body**:

```
📋 *Daily Action Plan* — {{1}}

You have *{{2}} items* today:
🔴 {{3}} High  •  🟡 {{4}} Medium  •  🟢 {{5}} Low

🔴 *HIGH PRIORITY*
{{6}}

🟡 *MEDIUM PRIORITY*
{{7}}

🟢 *LOW PRIORITY*
{{8}}

🤖 _Sent by Claude · Daily at 10 AM_
```

   - Variables: `{{1}}`=date, `{{2}}`=total, `{{3}}`=high count, `{{4}}`=medium count, `{{5}}`=low count, `{{6}}`=high items, `{{7}}`=medium items, `{{8}}`=low items
   - **Sample values** (required for approval): Fill each with realistic examples like `Thursday Apr 9`, `14`, `4`, `5`, `5`

4. Click **Submit for approval** → WhatsApp typically approves utility templates in minutes
5. After approval, copy the **Content SID** (starts with `HX...`)

> For production use, you'll also need a WhatsApp Business Account linked to Twilio.
> Guide: https://www.twilio.com/docs/whatsapp/self-sign-up

---

## PART 2 — Cursor Prompt

Copy everything below this line and paste into Cursor:

---

```
Implement a WhatsApp daily action plan dispatcher in the crux-ai FastAPI server.
The server is at D:\code\crux-ai, runs on 127.0.0.1:9090, uses FastAPI + pydantic-settings.
Follow the exact same code style as server/routes/speak.py.

---

## 1. Add dependency

In requirements.txt, add:
  twilio>=9.0.0

Install it:
  pip install twilio

---

## 2. Add config to server/config.py

Inside CruxSettings class, add a new section at the bottom before the closing:

  # WhatsApp (Twilio)
  WHATSAPP_ENABLED: bool = False
  WHATSAPP_ACCOUNT_SID: str = ""
  WHATSAPP_AUTH_TOKEN: str = ""
  WHATSAPP_FROM: str = "whatsapp:+14155238886"
  WHATSAPP_TO: str = ""
  # For production only — Content SID from Twilio Content Template Builder (HX...)
  # Leave empty to use free-form sandbox messages
  WHATSAPP_CONTENT_SID: str = ""

---

## 3. Create server/routes/whatsapp.py

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.config import get_settings

router = APIRouter(tags=["whatsapp"])
log = structlog.get_logger(__name__)


class ActionItem(BaseModel):
    priority: str
    subject: str
    from_: str = ""
    date: str = ""
    summary: str = ""
    action: str = ""


class DispatchPayload(BaseModel):
    generated_at: str
    total_items: int
    high_priority_count: int
    medium_priority_count: int
    low_priority_count: int
    whatsapp_message: str
    items: list[dict] = []


def _build_free_form_message(payload: DispatchPayload) -> str:
    """
    Build the WhatsApp-formatted message from payload.
    Used for sandbox (free-form). WhatsApp supports *bold* and _italic_.
    """
    return payload.whatsapp_message


@router.post("/whatsapp/dispatch")
async def whatsapp_dispatch(payload: DispatchPayload) -> dict:
    """
    Receive daily email action plan and send via WhatsApp (Twilio).

    Two modes:
    - Sandbox (WHATSAPP_CONTENT_SID empty): sends free-form message directly
    - Production (WHATSAPP_CONTENT_SID set): sends via approved Content Template

    Enable with WHATSAPP_ENABLED=true in .env
    """
    s = get_settings()

    if not s.WHATSAPP_ENABLED:
        log.info("whatsapp_dispatch_skipped", reason="WHATSAPP_ENABLED=false")
        return {"ok": True, "skipped": True, "reason": "WHATSAPP_ENABLED is false"}

    if not s.WHATSAPP_ACCOUNT_SID or not s.WHATSAPP_AUTH_TOKEN:
        raise HTTPException(status_code=503, detail="Twilio credentials not set — add WHATSAPP_ACCOUNT_SID and WHATSAPP_AUTH_TOKEN to .env")

    if not s.WHATSAPP_TO:
        raise HTTPException(status_code=503, detail="WHATSAPP_TO not set — add whatsapp:+91XXXXXXXXXX to .env")

    try:
        from twilio.rest import Client

        client = Client(s.WHATSAPP_ACCOUNT_SID, s.WHATSAPP_AUTH_TOKEN)

        if s.WHATSAPP_CONTENT_SID:
            # Production mode — use approved Content Template with variables
            high_items = "\n".join(
                f"*{i+1}. {it['subject']}*\n   From: {it.get('from', '')}\n   👉 _{it.get('action', '')}_"
                for i, it in enumerate(payload.items) if it.get("priority") == "HIGH"
            ) or "None today ✅"

            medium_items = "\n".join(
                f"*{i+1}. {it['subject']}*\n   From: {it.get('from', '')}\n   👉 _{it.get('action', '')}_"
                for i, it in enumerate(payload.items) if it.get("priority") == "MEDIUM"
            ) or "None today ✅"

            low_items = "\n".join(
                f"• {it['subject']}"
                for it in payload.items if it.get("priority") == "LOW"
            ) or "None today ✅"

            import re
            from datetime import datetime
            date_str = re.sub(r"T.*", "", payload.generated_at)
            try:
                date_str = datetime.fromisoformat(payload.generated_at).strftime("%A, %b %d")
            except Exception:
                pass

            message = client.messages.create(
                content_sid=s.WHATSAPP_CONTENT_SID,
                content_variables=str({
                    "1": date_str,
                    "2": str(payload.total_items),
                    "3": str(payload.high_priority_count),
                    "4": str(payload.medium_priority_count),
                    "5": str(payload.low_priority_count),
                    "6": high_items,
                    "7": medium_items,
                    "8": low_items,
                }).replace("'", '"'),
                from_=s.WHATSAPP_FROM,
                to=s.WHATSAPP_TO,
            )
        else:
            # Sandbox mode — free-form message, no template needed
            body = _build_free_form_message(payload)
            message = client.messages.create(
                body=body,
                from_=s.WHATSAPP_FROM,
                to=s.WHATSAPP_TO,
            )

        log.info(
            "whatsapp_sent",
            sid=message.sid,
            mode="template" if s.WHATSAPP_CONTENT_SID else "freeform",
            total=payload.total_items,
            high=payload.high_priority_count,
        )
        return {
            "ok": True,
            "sid": message.sid,
            "mode": "template" if s.WHATSAPP_CONTENT_SID else "freeform",
            "total_items": payload.total_items,
        }

    except Exception as exc:
        log.error("whatsapp_dispatch_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"WhatsApp send failed: {exc}") from exc


@router.get("/whatsapp/status")
async def whatsapp_status() -> dict:
    """Health check for WhatsApp config."""
    s = get_settings()
    return {
        "enabled": s.WHATSAPP_ENABLED,
        "from": s.WHATSAPP_FROM,
        "to_configured": bool(s.WHATSAPP_TO),
        "credentials_configured": bool(s.WHATSAPP_ACCOUNT_SID and s.WHATSAPP_AUTH_TOKEN),
        "mode": "template" if s.WHATSAPP_CONTENT_SID else "freeform_sandbox",
    }

---

## 4. Register router in server/main.py

Add import:
  from server.routes import git_routes, health, internal, llm, speak, whatsapp

Add router:
  app.include_router(whatsapp.router)

---

## 5. Add to .env and .env.example

# WhatsApp (Twilio) — https://console.twilio.com
WHATSAPP_ENABLED=true
WHATSAPP_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WHATSAPP_AUTH_TOKEN=your_auth_token_here
WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+919999999999
# Leave empty for sandbox. Set to HX... SID after template is approved for production.
WHATSAPP_CONTENT_SID=

---

## 6. Test it

# Check config:
curl http://127.0.0.1:9090/whatsapp/status

# Send a test message:
curl -X POST http://127.0.0.1:9090/whatsapp/dispatch \
  -H "Content-Type: application/json" \
  -d '{
    "generated_at": "2026-04-09T10:00:00+05:30",
    "total_items": 5,
    "high_priority_count": 2,
    "medium_priority_count": 2,
    "low_priority_count": 1,
    "whatsapp_message": "━━━━━━━━━━━━━━━━━━━━━\n📋 *DAILY ACTION PLAN*\n━━━━━━━━━━━━━━━━━━━━━\n📅 Thursday, Apr 9  •  10:00 AM IST\n👤 utkarsh.raj@lenskart.com\n\nYou have *5 items* today:\n🔴 2 High  •  🟡 2 Medium  •  🟢 1 Low\n━━━━━━━━━━━━━━━━━━━━━\n\n🔴 *HIGH PRIORITY*\n\n*1. Test item one*\n   From: someone@lenskart.com\n   ⏰ TODAY\n   👉 _Reply now_\n\n━━━━━━━━━━━━━━━━━━━━━\n🤖 _Sent by Claude · Daily at 10 AM_",
    "items": [
      {"priority": "HIGH", "subject": "Test item one", "from": "someone@lenskart.com", "action": "Reply now"},
      {"priority": "HIGH", "subject": "Test item two", "from": "boss@lenskart.com", "action": "Review and approve"}
    ]
  }'

Expected: {"ok": true, "sid": "SMxxx...", "mode": "freeform_sandbox", "total_items": 5}
```

---

## PART 3 — Production Upgrade Checklist

When you're ready to go beyond sandbox:
- [ ] Apply for WhatsApp Business Account via Twilio: https://www.twilio.com/whatsapp/request-access
- [ ] Submit `daily_action_plan` template in Content Template Builder (Category: UTILITY)
- [ ] Wait for approval (usually minutes via ML review)
- [ ] Set `WHATSAPP_CONTENT_SID=HXxxxxxxx` in `.env`
- [ ] Change `WHATSAPP_FROM` to your approved business number

Sources:
- [Twilio Content Template Builder](https://www.twilio.com/docs/content/create-templates-with-the-content-template-builder)
- [WhatsApp Template Best Practices](https://help.twilio.com/articles/360039737753-Recommendations-and-Best-Practices-for-Creating-WhatsApp-Message-Templates)
- [Send WhatsApp Notification Messages](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates)
