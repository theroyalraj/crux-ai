# WhatsApp Action Plan — Full Inbound System
## Cursor Implementation Plan

---

## Architecture Overview

```
Gmail ──► Claude Scheduled Task (10 AM + hourly)
              │
              ▼
         crux-ai server (FastAPI :9090)
              │
         Postgres (action_items, daily_runs)
              │
         Twilio WhatsApp API ──► Your Phone
              │
         (inbound reply)
              │
         Twilio Webhook ──► n8n (public webhook)
                                │
                          crux-ai /action/* API
                                │
                          Twilio send reply ──► Your Phone
```

**Responsibilities:**
| Component | Does |
|-----------|------|
| Claude scheduled task (10 AM) | AI Gmail scan → numbered action plan → POST /whatsapp/dispatch |
| Claude scheduled task (hourly) | AI Gmail delta scan → POST /whatsapp/dispatch-delta if new HIGH/MEDIUM |
| crux-ai server | Stores items in Postgres, sends WhatsApp, exposes action APIs |
| n8n Flow 1 | Public Twilio inbound webhook → parse reply → call crux-ai → send reply |
| n8n Flow 2 | 7PM cron → call crux-ai /action/summary → send WhatsApp |
| Postgres | Persists action_items + daily_runs per day |

---

## WhatsApp Message Formats

### Morning / Delta (numbered bullets)
```
📋 *Action Plan* — Thu, Apr 9
*9 items:* 🔴4 High • 🟡3 Medium • 🟢2 Low
━━━━━━━━━━━━━━━
🔴 *HIGH*
1. Performance Cycle FY'26 closes TODAY 3–6PM
2. Chaitanya commented on wallet payout cron — awaiting response
3. Margin Invoice — Bito flagged issues + new commits by Tanishka
4. Recovery amount credit limit fix — Bito review just started
━━━━━━━━━━━━━━━
🟡 *MEDIUM*
5. Tech Planning with Divya TODAY 4–4:30PM
6. Net Take Home Discussions with Divya TODAY 4–5PM
7. Ezetapcard refund — HDFC + Razorpay active, Amit leading
━━━━━━━━━━━━━━━
🟢 *LOW*
8. Daily commission run OK — 308 franchises processed
9. Bank deposit slips routine + helm cron disabled in prod
━━━━━━━━━━━━━━━
_Reply 1 3 5 to mark done · /action for status_
```

### Hourly Delta (only new items, continuing numbering)
```
🔔 *2 new items* — 2:00 PM update
━━━━━━━━━━━━━━━
🔴 *HIGH*
10. Divya flagged invoice discrepancy — needs your response
🟡 *MEDIUM*
11. Deployment approval pending in DevOps space
━━━━━━━━━━━━━━━
_Reply 10 11 to mark done · /action for full status_
```

### /action Status Response
```
📋 *Status* — Thu, Apr 9
✅ 3 done · ⏳ 6 pending
━━━━━━━━━━━━━━━
🔴 *HIGH*
✅ ~1. Performance Cycle FY'26~
2. Chaitanya — wallet payout cron
3. Margin Invoice — Bito review
4. Recovery amount fix
━━━━━━━━━━━━━━━
🟡 *MEDIUM*
✅ ~5. Tech Planning 4PM~
6. Net Take Home 4PM
7. Ezetapcard refund thread
━━━━━━━━━━━━━━━
🟢 *LOW*
8. Commission OK
9. Bank slips + helm merged
━━━━━━━━━━━━━━━
```
> WhatsApp strikethrough = `~text~` (single tilde)

### 7PM Day Summary
```
🌆 *Day Summary* — Thu, Apr 9
*9 items:* ✅ 4 done · ⏳ 5 still open
━━━━━━━━━━━━━━━
⏳ *Still open*
🔴 2. Chaitanya — wallet payout cron
🔴 3. Margin Invoice — Bito review
🟡 7. Ezetapcard refund thread
🟢 9. Bank slips + helm
━━━━━━━━━━━━━━━
✅ *Closed today* — 1, 4, 5, 6
━━━━━━━━━━━━━━━
```

---

## Part 1 — Postgres Schema Migration

Create file `server/db/migrations/001_action_items.sql`:

```sql
CREATE TABLE IF NOT EXISTS action_items (
    id          SERIAL PRIMARY KEY,
    date        DATE        NOT NULL,
    number      INTEGER     NOT NULL,          -- 1-based sequential number per day
    priority    VARCHAR(10) NOT NULL,          -- HIGH | MEDIUM | LOW
    subject     TEXT        NOT NULL,
    from_email  VARCHAR(255),
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending | done
    source      VARCHAR(20) NOT NULL DEFAULT 'gmail',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    done_at     TIMESTAMPTZ,
    UNIQUE (date, number)
);

CREATE INDEX IF NOT EXISTS idx_action_items_date ON action_items (date);
CREATE INDEX IF NOT EXISTS idx_action_items_date_status ON action_items (date, status);

CREATE TABLE IF NOT EXISTS daily_runs (
    id              SERIAL PRIMARY KEY,
    date            DATE        NOT NULL,
    run_type        VARCHAR(20) NOT NULL,      -- morning | hourly | evening
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    item_count      INTEGER     NOT NULL DEFAULT 0,
    new_item_count  INTEGER     NOT NULL DEFAULT 0,
    whatsapp_sent   BOOLEAN     NOT NULL DEFAULT FALSE,
    char_count      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_daily_runs_date ON daily_runs (date);
```

Run this on startup — add to `server/db/postgres.py` `init_postgres()`:
```python
async def run_migrations(pool: asyncpg.Pool) -> None:
    migration_path = Path(__file__).parent / "migrations" / "001_action_items.sql"
    sql = migration_path.read_text()
    async with pool.acquire() as conn:
        await conn.execute(sql)
```

---

## Part 2 — Config additions (`server/config.py`)

Add to `CruxSettings`:
```python
# WhatsApp / Twilio
WHATSAPP_ENABLED: bool = False
WHATSAPP_ACCOUNT_SID: str = ""
WHATSAPP_AUTH_TOKEN: str = ""
WHATSAPP_FROM: str = "whatsapp:+14155238886"   # Twilio sandbox number
WHATSAPP_TO: str = ""                           # Your number e.g. whatsapp:+919XXXXXXXXX
WHATSAPP_CONTENT_SID: str = ""                  # Leave empty for sandbox free-form

# Action system
ACTION_DAILY_RESET_HOUR_IST: int = 10           # Fresh numbering starts at 10 AM IST
```

Add to `.env`:
```
WHATSAPP_ENABLED=true
WHATSAPP_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WHATSAPP_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WHATSAPP_FROM=whatsapp:+14155238886
WHATSAPP_TO=whatsapp:+91XXXXXXXXXX
WHATSAPP_CONTENT_SID=
```

---

## Part 3 — Pydantic Models (`server/models/action.py`) [NEW FILE]

```python
from __future__ import annotations
from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel


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
    whatsapp_message: str          # built by Claude scheduled task
    items: list[ActionItem]


class MarkDoneRequest(BaseModel):
    numbers: list[int]             # e.g. [1, 3, 5]


class ActionStatusItem(BaseModel):
    number: int
    priority: str
    subject: str
    status: str                    # pending | done
    done_at: datetime | None = None


class DeltaResponse(BaseModel):
    has_new_items: bool
    has_high: bool
    has_medium: bool
    new_items: list[ActionStatusItem]
    next_number: int               # for numbering delta items
```

---

## Part 4 — WhatsApp Routes (`server/routes/whatsapp.py`) [FULL REWRITE]

```python
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse
from twilio.rest import Client

from server.config import get_settings
from server.db import get_pool
from server.models.action import (
    ActionItem,
    ActionStatusItem,
    DeltaResponse,
    DispatchPayload,
    MarkDoneRequest,
)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

IST = ZoneInfo("Asia/Kolkata")
PRIORITY_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}


def _twilio_client():
    s = get_settings()
    return Client(s.WHATSAPP_ACCOUNT_SID, s.WHATSAPP_AUTH_TOKEN)


def _ist_now() -> datetime:
    return datetime.now(tz=IST)


def _today_ist() -> date:
    return _ist_now().date()


# ─────────────────────────── helpers ──────────────────────────────────────────

async def _get_today_items(conn, for_date: date) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT number, priority, subject, status, done_at
        FROM action_items
        WHERE date = $1
        ORDER BY number
        """,
        for_date,
    )
    return [dict(r) for r in rows]


async def _next_number_for_today(conn, for_date: date) -> int:
    row = await conn.fetchrow(
        "SELECT COALESCE(MAX(number), 0) + 1 AS next FROM action_items WHERE date = $1",
        for_date,
    )
    return row["next"]


def _build_status_message(items: list[dict], for_date: date) -> str:
    done = [i for i in items if i["status"] == "done"]
    pending = [i for i in items if i["status"] == "pending"]
    day_str = for_date.strftime("%a, %b %-d")

    lines = [
        f"📋 *Status* — {day_str}",
        f"✅ {len(done)} done · ⏳ {len(pending)} pending",
        "━━━━━━━━━━━━━━━",
    ]

    for priority in ["HIGH", "MEDIUM", "LOW"]:
        grp = [i for i in items if i["priority"] == priority]
        if not grp:
            continue
        lines.append(f"{PRIORITY_EMOJI[priority]} *{priority}*")
        for i in grp:
            if i["status"] == "done":
                lines.append(f"✅ ~{i['number']}. {i['subject']}~")
            else:
                lines.append(f"{i['number']}. {i['subject']}")
        lines.append("━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def _build_summary_message(items: list[dict], for_date: date) -> str:
    done = [i for i in items if i["status"] == "done"]
    pending = [i for i in items if i["status"] == "pending"]
    day_str = for_date.strftime("%a, %b %-d")

    lines = [
        f"🌆 *Day Summary* — {day_str}",
        f"*{len(items)} items:* ✅ {len(done)} done · ⏳ {len(pending)} still open",
        "━━━━━━━━━━━━━━━",
    ]

    if pending:
        lines.append("⏳ *Still open*")
        for i in pending:
            emoji = PRIORITY_EMOJI.get(i["priority"], "")
            lines.append(f"{emoji} {i['number']}. {i['subject']}")
        lines.append("━━━━━━━━━━━━━━━")

    if done:
        done_nums = ", ".join(str(i["number"]) for i in done)
        lines.append(f"✅ *Closed today* — {done_nums}")
        lines.append("━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def _send_whatsapp(message: str) -> str:
    s = get_settings()
    client = _twilio_client()
    if s.WHATSAPP_CONTENT_SID:
        # Production template path (not used for these dynamic messages)
        raise NotImplementedError("Content SID not supported for dynamic messages")
    msg = client.messages.create(
        body=message,
        from_=s.WHATSAPP_FROM,
        to=s.WHATSAPP_TO,
    )
    return msg.sid


# ─────────────────────────── POST /whatsapp/dispatch ──────────────────────────

@router.post("/dispatch")
async def whatsapp_dispatch(payload: DispatchPayload) -> dict:
    """
    Called by Claude scheduled task at 10 AM.
    Stores items in Postgres with sequential numbers, sends WhatsApp.
    The whatsapp_message from Claude is rebuilt here with numbers injected.
    """
    s = get_settings()
    pool = get_pool()
    today = _today_ist()
    day_str = today.strftime("%a, %b %-d")

    # Assign sequential numbers starting from 1 (or continue if already items today)
    async with pool.acquire() as conn:
        start_num = await _next_number_for_today(conn, today)

        numbered_items: list[tuple[int, ActionItem]] = []
        for idx, item in enumerate(payload.items):
            num = start_num + idx
            numbered_items.append((num, item))
            await conn.execute(
                """
                INSERT INTO action_items (date, number, priority, subject, from_email, status)
                VALUES ($1, $2, $3, $4, $5, 'pending')
                ON CONFLICT (date, number) DO NOTHING
                """,
                today, num, item.priority, item.subject, item.from_email,
            )

        # Log the run
        await conn.execute(
            """
            INSERT INTO daily_runs (date, run_type, item_count, new_item_count, char_count)
            VALUES ($1, 'morning', $2, $3, $4)
            """,
            today, len(payload.items), len(payload.items), payload.char_count,
        )

    # Build numbered WhatsApp message
    h = [(n, i) for n, i in numbered_items if i.priority == "HIGH"]
    m = [(n, i) for n, i in numbered_items if i.priority == "MEDIUM"]
    l = [(n, i) for n, i in numbered_items if i.priority == "LOW"]

    lines = [
        f"📋 *Action Plan* — {day_str}",
        f"*{len(numbered_items)} items:* 🔴{len(h)} High • 🟡{len(m)} Medium • 🟢{len(l)} Low",
        "━━━━━━━━━━━━━━━",
    ]
    if h:
        lines.append("🔴 *HIGH*")
        lines.extend(f"{n}. {i.subject}" for n, i in h)
        lines.append("━━━━━━━━━━━━━━━")
    if m:
        lines.append("🟡 *MEDIUM*")
        lines.extend(f"{n}. {i.subject}" for n, i in m)
        lines.append("━━━━━━━━━━━━━━━")
    if l:
        lines.append("🟢 *LOW*")
        lines.extend(f"{n}. {i.subject}" for n, i in l)
        lines.append("━━━━━━━━━━━━━━━")
    lines.append("_Reply 1 3 5 to mark done · /action for status_")

    message = "\n".join(lines)
    assert len(message) <= 1024, f"Message too long: {len(message)} chars"

    sid = None
    if s.WHATSAPP_ENABLED:
        sid = _send_whatsapp(message)
        log.info("whatsapp_dispatched", sid=sid, chars=len(message))

    return {"ok": True, "sid": sid, "char_count": len(message), "items": len(numbered_items)}


# ─────────────────────────── POST /whatsapp/dispatch-delta ────────────────────

@router.post("/dispatch-delta")
async def whatsapp_dispatch_delta(payload: DispatchPayload) -> dict:
    """
    Called by Claude hourly task when new HIGH/MEDIUM items found.
    Continues numbering from where today's items left off.
    """
    s = get_settings()
    pool = get_pool()
    today = _today_ist()
    now_str = _ist_now().strftime("%-I:%M %p")

    async with pool.acquire() as conn:
        start_num = await _next_number_for_today(conn, today)

        numbered_items: list[tuple[int, ActionItem]] = []
        for idx, item in enumerate(payload.items):
            num = start_num + idx
            numbered_items.append((num, item))
            await conn.execute(
                """
                INSERT INTO action_items (date, number, priority, subject, from_email, status)
                VALUES ($1, $2, $3, $4, $5, 'pending')
                ON CONFLICT (date, number) DO NOTHING
                """,
                today, num, item.priority, item.subject, item.from_email,
            )

        await conn.execute(
            """
            INSERT INTO daily_runs (date, run_type, new_item_count, whatsapp_sent)
            VALUES ($1, 'hourly', $2, $3)
            """,
            today, len(payload.items), s.WHATSAPP_ENABLED,
        )

    h = [(n, i) for n, i in numbered_items if i.priority == "HIGH"]
    m = [(n, i) for n, i in numbered_items if i.priority == "MEDIUM"]

    lines = [f"🔔 *{len(numbered_items)} new item{'s' if len(numbered_items) > 1 else ''}* — {now_str} update", "━━━━━━━━━━━━━━━"]
    if h:
        lines.append("🔴 *HIGH*")
        lines.extend(f"{n}. {i.subject}" for n, i in h)
        lines.append("━━━━━━━━━━━━━━━")
    if m:
        lines.append("🟡 *MEDIUM*")
        lines.extend(f"{n}. {i.subject}" for n, i in m)
        lines.append("━━━━━━━━━━━━━━━")
    lines.append("_Reply numbers to mark done · /action for full status_")

    message = "\n".join(lines)
    sid = None
    if s.WHATSAPP_ENABLED:
        sid = _send_whatsapp(message)

    return {"ok": True, "sid": sid, "char_count": len(message)}


# ─────────────────────────── POST /whatsapp/dispatch-summary ──────────────────

@router.post("/dispatch-summary")
async def whatsapp_dispatch_summary() -> dict:
    """Called by n8n at 7 PM IST. Reads Postgres, sends day summary."""
    s = get_settings()
    pool = get_pool()
    today = _today_ist()

    async with pool.acquire() as conn:
        items = await _get_today_items(conn, today)
        await conn.execute(
            "INSERT INTO daily_runs (date, run_type, item_count, whatsapp_sent) VALUES ($1, 'evening', $2, $3)",
            today, len(items), s.WHATSAPP_ENABLED,
        )

    if not items:
        return {"ok": True, "message": "No items today"}

    message = _build_summary_message(items, today)
    sid = None
    if s.WHATSAPP_ENABLED:
        sid = _send_whatsapp(message)

    return {"ok": True, "sid": sid, "char_count": len(message)}


# ─────────────────────────── GET /action/today ────────────────────────────────

@router.get("/action/today")
async def action_today() -> dict:
    """Returns today's items with status. n8n calls this for /action command."""
    pool = get_pool()
    today = _today_ist()
    async with pool.acquire() as conn:
        items = await _get_today_items(conn, today)
    message = _build_status_message(items, today)
    return {
        "date": str(today),
        "items": items,
        "whatsapp_message": message,
        "char_count": len(message),
    }


# ─────────────────────────── POST /action/mark-done ──────────────────────────

@router.post("/action/mark-done")
async def action_mark_done(req: MarkDoneRequest) -> dict:
    """Mark items done by number. n8n calls this when user replies with numbers."""
    pool = get_pool()
    today = _today_ist()
    now = _ist_now()

    async with pool.acquire() as conn:
        updated = []
        for num in req.numbers:
            result = await conn.execute(
                """
                UPDATE action_items
                SET status = 'done', done_at = $1
                WHERE date = $2 AND number = $3 AND status = 'pending'
                """,
                now, today, num,
            )
            if result != "UPDATE 0":
                updated.append(num)

    if updated:
        nums = ", ".join(str(n) for n in updated)
        reply = f"✅ Marked done: {nums}"
    else:
        reply = "⚠️ No matching pending items found"

    return {"ok": True, "updated": updated, "reply_message": reply}


# ─────────────────────────── GET /action/delta ────────────────────────────────

@router.get("/action/delta")
async def action_delta() -> dict:
    """
    Returns new HIGH/MEDIUM items added since the last hourly run.
    Claude hourly task calls this to check if a WhatsApp alert is needed.
    Also used by n8n hourly trigger.
    """
    pool = get_pool()
    today = _today_ist()

    async with pool.acquire() as conn:
        # Get timestamp of last morning or hourly run
        last_run = await conn.fetchrow(
            """
            SELECT run_at FROM daily_runs
            WHERE date = $1 AND run_type IN ('morning', 'hourly')
            ORDER BY run_at DESC LIMIT 1
            """,
            today,
        )
        last_run_at = last_run["run_at"] if last_run else None

        if last_run_at:
            new_rows = await conn.fetch(
                """
                SELECT number, priority, subject, status, done_at
                FROM action_items
                WHERE date = $1 AND created_at > $2
                ORDER BY number
                """,
                today, last_run_at,
            )
        else:
            new_rows = []

        next_num = await _next_number_for_today(conn, today)

    new_items = [dict(r) for r in new_rows]
    high_medium = [i for i in new_items if i["priority"] in ("HIGH", "MEDIUM")]

    return DeltaResponse(
        has_new_items=len(new_items) > 0,
        has_high=any(i["priority"] == "HIGH" for i in new_items),
        has_medium=any(i["priority"] == "MEDIUM" for i in new_items),
        new_items=[ActionStatusItem(**i) for i in new_items],
        next_number=next_num,
    ).model_dump()


# ─────────────────────────── POST /whatsapp/inbound (Twilio TwiML) ────────────

@router.post("/inbound", response_class=PlainTextResponse)
async def whatsapp_inbound(
    Body: str = Form(""),
    From: str = Form(""),
):
    """
    Optional: Direct Twilio webhook (if crux-ai is exposed via ngrok).
    Prefer the n8n flow instead for local setups.
    """
    body = Body.strip()
    pool = get_pool()
    today = _today_ist()

    if body.lower() == "/action":
        async with pool.acquire() as conn:
            items = await _get_today_items(conn, today)
        reply = _build_status_message(items, today)

    elif re.match(r"^[\d\s]+$", body):
        numbers = [int(x) for x in body.split()]
        async with pool.acquire() as conn:
            updated = []
            for num in numbers:
                result = await conn.execute(
                    "UPDATE action_items SET status='done', done_at=NOW() WHERE date=$1 AND number=$2 AND status='pending'",
                    today, num,
                )
                if result != "UPDATE 0":
                    updated.append(num)
        if updated:
            reply = f"✅ Marked done: {', '.join(str(n) for n in updated)}"
        else:
            reply = "⚠️ No matching pending items"
    else:
        return PlainTextResponse("<?xml version='1.0'?><Response></Response>", media_type="text/xml")

    twiml = f"""<?xml version='1.0'?>
<Response>
  <Message>{reply}</Message>
</Response>"""
    return PlainTextResponse(twiml, media_type="text/xml")


# ─────────────────────────── GET /whatsapp/status ─────────────────────────────

@router.get("/status")
async def whatsapp_status() -> dict:
    s = get_settings()
    pool = get_pool()
    today = _today_ist()

    async with pool.acquire() as conn:
        items = await _get_today_items(conn, today)
        runs = await conn.fetch(
            "SELECT run_type, run_at, item_count, whatsapp_sent FROM daily_runs WHERE date=$1 ORDER BY run_at",
            today,
        )

    return {
        "enabled": s.WHATSAPP_ENABLED,
        "today": str(today),
        "item_count": len(items),
        "done_count": sum(1 for i in items if i["status"] == "done"),
        "pending_count": sum(1 for i in items if i["status"] == "pending"),
        "runs": [dict(r) for r in runs],
    }
```

---

## Part 5 — Update `server/main.py`

Replace the whatsapp router import/include:
```python
from server.routes import whatsapp
# already present — just make sure action routes are on the same router
app.include_router(whatsapp.router)
```

The `GET /action/today`, `POST /action/mark-done`, `GET /action/delta` routes are all on the `whatsapp.router` with prefix `/whatsapp`, so their full paths are:
- `GET /whatsapp/action/today`
- `POST /whatsapp/action/mark-done`
- `GET /whatsapp/action/delta`

Alternatively, create a separate `action.router` with prefix `/action` and include it:
```python
from server.routes import whatsapp, action as action_routes
app.include_router(action_routes.router)  # prefix /action
```

---

## Part 6 — n8n Flows

### Prerequisites
- n8n running locally on port 5678
- Expose n8n publicly: `ngrok http 5678` (get URL like `https://abc123.ngrok.io`)
- In Twilio Sandbox: set "When a message comes in" webhook to `https://abc123.ngrok.io/webhook/whatsapp-inbound`

---

### n8n Flow 1: Inbound WhatsApp Handler

**Import this JSON into n8n (Settings → Import Workflow):**

```json
{
  "name": "WhatsApp Inbound Handler",
  "nodes": [
    {
      "name": "Twilio Webhook",
      "type": "n8n-nodes-base.webhook",
      "position": [200, 300],
      "parameters": {
        "path": "whatsapp-inbound",
        "httpMethod": "POST",
        "responseMode": "responseNode"
      }
    },
    {
      "name": "Parse Body",
      "type": "n8n-nodes-base.set",
      "position": [420, 300],
      "parameters": {
        "values": {
          "string": [
            { "name": "body", "value": "={{ $json.body.Body.trim() }}" },
            { "name": "from", "value": "={{ $json.body.From }}" }
          ]
        }
      }
    },
    {
      "name": "Is /action?",
      "type": "n8n-nodes-base.if",
      "position": [640, 300],
      "parameters": {
        "conditions": {
          "string": [{ "value1": "={{ $json.body }}", "operation": "equal", "value2": "/action" }]
        }
      }
    },
    {
      "name": "Get Today Status",
      "type": "n8n-nodes-base.httpRequest",
      "position": [860, 180],
      "parameters": {
        "url": "http://127.0.0.1:9090/whatsapp/action/today",
        "method": "GET"
      }
    },
    {
      "name": "Is Numbers?",
      "type": "n8n-nodes-base.if",
      "position": [860, 420],
      "parameters": {
        "conditions": {
          "string": [{ "value1": "={{ $json.body }}", "operation": "regex", "value2": "^[\\d\\s]+$" }]
        }
      }
    },
    {
      "name": "Mark Done",
      "type": "n8n-nodes-base.httpRequest",
      "position": [1080, 360],
      "parameters": {
        "url": "http://127.0.0.1:9090/whatsapp/action/mark-done",
        "method": "POST",
        "jsonParameters": true,
        "bodyParametersJson": "={{ JSON.stringify({ numbers: $json.body.split(' ').map(Number) }) }}"
      }
    },
    {
      "name": "Send Status Reply",
      "type": "n8n-nodes-base.httpRequest",
      "position": [1080, 180],
      "parameters": {
        "url": "https://api.twilio.com/2010-04-01/Accounts/{{ $env.TWILIO_SID }}/Messages.json",
        "method": "POST",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpBasicAuth",
        "bodyParametersUi": {
          "parameter": [
            { "name": "From", "value": "={{ $env.WHATSAPP_FROM }}" },
            { "name": "To", "value": "={{ $node['Parse Body'].json.from }}" },
            { "name": "Body", "value": "={{ $json.whatsapp_message }}" }
          ]
        }
      }
    },
    {
      "name": "Send Done Reply",
      "type": "n8n-nodes-base.httpRequest",
      "position": [1300, 360],
      "parameters": {
        "url": "https://api.twilio.com/2010-04-01/Accounts/{{ $env.TWILIO_SID }}/Messages.json",
        "method": "POST",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpBasicAuth",
        "bodyParametersUi": {
          "parameter": [
            { "name": "From", "value": "={{ $env.WHATSAPP_FROM }}" },
            { "name": "To", "value": "={{ $node['Parse Body'].json.from }}" },
            { "name": "Body", "value": "={{ $json.reply_message }}" }
          ]
        }
      }
    },
    {
      "name": "Respond 200",
      "type": "n8n-nodes-base.respondToWebhook",
      "position": [1500, 300],
      "parameters": { "respondWith": "noData" }
    }
  ],
  "connections": {
    "Twilio Webhook": { "main": [[{ "node": "Parse Body", "type": "main", "index": 0 }]] },
    "Parse Body": { "main": [[{ "node": "Is /action?", "type": "main", "index": 0 }]] },
    "Is /action?": {
      "main": [
        [{ "node": "Get Today Status", "type": "main", "index": 0 }],
        [{ "node": "Is Numbers?", "type": "main", "index": 0 }]
      ]
    },
    "Get Today Status": { "main": [[{ "node": "Send Status Reply", "type": "main", "index": 0 }]] },
    "Is Numbers?": {
      "main": [
        [{ "node": "Mark Done", "type": "main", "index": 0 }],
        [{ "node": "Respond 200", "type": "main", "index": 0 }]
      ]
    },
    "Mark Done": { "main": [[{ "node": "Send Done Reply", "type": "main", "index": 0 }]] },
    "Send Status Reply": { "main": [[{ "node": "Respond 200", "type": "main", "index": 0 }]] },
    "Send Done Reply": { "main": [[{ "node": "Respond 200", "type": "main", "index": 0 }]] }
  }
}
```

---

### n8n Flow 2: 7PM Day Summary

```json
{
  "name": "WhatsApp 7PM Summary",
  "nodes": [
    {
      "name": "7PM Cron",
      "type": "n8n-nodes-base.scheduleTrigger",
      "position": [200, 300],
      "parameters": {
        "rule": { "interval": [{ "field": "cronExpression", "expression": "30 13 * * *" }] }
      }
    },
    {
      "name": "Send Summary",
      "type": "n8n-nodes-base.httpRequest",
      "position": [420, 300],
      "parameters": {
        "url": "http://127.0.0.1:9090/whatsapp/dispatch-summary",
        "method": "POST"
      }
    }
  ],
  "connections": {
    "7PM Cron": { "main": [[{ "node": "Send Summary", "type": "main", "index": 0 }]] }
  }
}
```
> Cron `30 13 * * *` = 7:00 PM IST (UTC+5:30)

---

## Part 7 — Update Claude Scheduled Tasks

### Update `daily-email-action-plan` prompt addition
The existing prompt already builds `items[]` in the JSON. The server now handles numbering automatically — Claude just needs to POST the items without numbers. No change needed to the scheduled task prompt.

### New task: `hourly-email-delta`
Cron: `0 11-18 * * *` (11 AM – 6 PM IST daily)

**Prompt:**
```
Hourly Gmail delta check. Only send WhatsApp if genuinely new HIGH or MEDIUM items found.

STEP 1 — Check what's already tracked today
Call GET http://127.0.0.1:9090/whatsapp/action/today
Note existing subjects to avoid duplicates.

STEP 2 — Scan Gmail for new items (last 2 hours)
Search: is:unread newer_than:2h
Search: is:inbox -is:sent newer_than:2h -label:replied

STEP 3 — Compare
Identify items NOT already in today's list.
Classify: HIGH | MEDIUM | LOW (same rules as morning).
Skip LOW-only updates — not worth a WhatsApp ping.

STEP 4 — If new HIGH or MEDIUM found:
Build items[] array (same format as morning dispatch).
Build whatsapp_message using same rules (numbered, <1024 chars, no footer, no MR numbers).
POST http://127.0.0.1:9090/whatsapp/dispatch-delta with the payload.

STEP 5 — If nothing new: print "No new items — skipping WhatsApp" and stop.

Report: new item count, sent or skipped, char count.
```

---

## Part 8 — Full Test Checklist

```bash
# 1. Run migration
psql $DATABASE_URL -f server/db/migrations/001_action_items.sql

# 2. Test morning dispatch
curl -X POST http://127.0.0.1:9090/whatsapp/dispatch \
  -H "Content-Type: application/json" \
  -d @D:\code\crux-ai\var\action_plan_2026-04-09_10-00.json

# 3. Check today's items
curl http://127.0.0.1:9090/whatsapp/action/today

# 4. Mark items done
curl -X POST http://127.0.0.1:9090/whatsapp/action/mark-done \
  -H "Content-Type: application/json" \
  -d '{"numbers": [1, 3]}'

# 5. Check /action status message
curl http://127.0.0.1:9090/whatsapp/action/today | jq .whatsapp_message

# 6. Trigger 7PM summary
curl -X POST http://127.0.0.1:9090/whatsapp/dispatch-summary

# 7. Test inbound webhook (simulate Twilio)
curl -X POST http://localhost:5678/webhook/whatsapp-inbound \
  -d "Body=1 3&From=whatsapp:+91XXXXXXXXXX"

curl -X POST http://localhost:5678/webhook/whatsapp-inbound \
  -d "Body=/action&From=whatsapp:+91XXXXXXXXXX"
```

---

## Summary of All New/Changed Files

| File | Action |
|------|--------|
| `server/db/migrations/001_action_items.sql` | NEW — schema |
| `server/db/postgres.py` | MODIFY — add `run_migrations()` call |
| `server/config.py` | MODIFY — add WhatsApp + Action settings |
| `server/models/action.py` | NEW — Pydantic models |
| `server/routes/whatsapp.py` | REWRITE — all new endpoints |
| `server/main.py` | MODIFY — include action router if split |
| `.env` | MODIFY — add Twilio + WhatsApp vars |
| n8n Flow 1 (import JSON) | NEW — inbound handler |
| n8n Flow 2 (import JSON) | NEW — 7PM summary |
| Claude task `hourly-email-delta` | NEW — scheduled hourly delta |
