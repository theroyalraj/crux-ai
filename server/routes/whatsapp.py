from __future__ import annotations

import html
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
import structlog
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import PlainTextResponse

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

# Windows needs the tzdata package for IANA names; fallback is fixed IST (no DST).
try:
    IST = ZoneInfo("Asia/Kolkata")
except ZoneInfoNotFoundError:
    IST = timezone(timedelta(hours=5, minutes=30))

PRIORITY_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}


def _parse_mark_done_numbers(body: str) -> list[int] | None:
    """Parse mark-done replies: '8', '1 3 5', '8 done', 'done 1 2'. None if not that intent."""
    b = body.strip()
    if not b:
        return None
    if re.fullmatch(r"[\d\s]+", b):
        return [int(x) for x in b.split()]
    for pat in (
        r"(?i)^([\d\s]+)\s+done\s*$",
        r"(?i)^done\s+([\d\s]+)\s*$",
        r"(?i)^mark\s+([\d\s]+)(?:\s+done)?\s*$",
    ):
        m = re.match(pat, b)
        if m:
            inner = m.group(1).strip()
            if re.fullmatch(r"[\d\s]+", inner):
                return [int(x) for x in inner.split()]
    return None


def _require_pool() -> asyncpg.Pool:
    pool = get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    return pool


def _format_day(d: date) -> str:
    """Cross-platform 'Thu, Apr 9' (avoid %-d which is Unix-only)."""
    return f"{d:%a, %b} {d.day}"


def _format_time_12h(dt: datetime) -> str:
    """e.g. '2:00 PM' without strftime platform quirks."""
    h24 = dt.hour
    h12 = h24 % 12 or 12
    am_pm = "AM" if h24 < 12 else "PM"
    return f"{h12}:{dt.minute:02d} {am_pm}"


def _twilio_client():
    s = get_settings()
    from twilio.rest import Client

    return Client(s.WHATSAPP_ACCOUNT_SID, s.WHATSAPP_AUTH_TOKEN)


def _ist_now() -> datetime:
    return datetime.now(tz=IST)


def _today_ist() -> date:
    return _ist_now().date()


async def _get_today_items(conn: asyncpg.Connection, for_date: date) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT number, priority, subject, status, done_at
        FROM crux_action_items
        WHERE plan_date = $1
        ORDER BY number
        """,
        for_date,
    )
    return [dict(r) for r in rows]


async def _next_number_for_today(conn: asyncpg.Connection, for_date: date) -> int:
    row = await conn.fetchrow(
        "SELECT COALESCE(MAX(number), 0) + 1 AS next FROM crux_action_items WHERE plan_date = $1",
        for_date,
    )
    assert row is not None
    return row["next"]


def _build_status_message(items: list[dict], for_date: date) -> str:
    done = [i for i in items if i["status"] == "done"]
    pending = [i for i in items if i["status"] == "pending"]
    day_str = _format_day(for_date)

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
    day_str = _format_day(for_date)

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
    if s.WHATSAPP_CONTENT_SID:
        raise HTTPException(
            status_code=501,
            detail="WHATSAPP_CONTENT_SID is set; dynamic action messages require free-form body. "
            "Clear WHATSAPP_CONTENT_SID for sandbox, or send these flows outside template mode.",
        )
    client = _twilio_client()
    msg = client.messages.create(
        body=message,
        from_=s.WHATSAPP_FROM,
        to=s.WHATSAPP_TO,
    )
    return msg.sid


@router.post("/dispatch")
async def whatsapp_dispatch(payload: DispatchPayload) -> dict:
    """Morning run: store items, send numbered WhatsApp."""
    s = get_settings()
    pool = _require_pool()
    today = _today_ist()
    day_str = _format_day(today)

    async with pool.acquire() as conn:
        start_num = await _next_number_for_today(conn, today)

        numbered_items: list[tuple[int, ActionItem]] = []
        for idx, item in enumerate(payload.items):
            num = start_num + idx
            numbered_items.append((num, item))
            await conn.execute(
                """
                INSERT INTO crux_action_items (
                    plan_date, number, priority, subject, from_email, status
                )
                VALUES ($1, $2, $3, $4, $5, 'pending')
                ON CONFLICT (plan_date, number) DO NOTHING
                """,
                today,
                num,
                item.priority,
                item.subject,
                item.from_email or None,
            )

        await conn.execute(
            """
            INSERT INTO crux_daily_runs (
                plan_date, run_type, item_count, new_item_count, char_count
            )
            VALUES ($1, 'morning', $2, $3, $4)
            """,
            today,
            len(payload.items),
            len(payload.items),
            payload.char_count,
        )

    high = [(n, i) for n, i in numbered_items if i.priority == "HIGH"]
    med = [(n, i) for n, i in numbered_items if i.priority == "MEDIUM"]
    low = [(n, i) for n, i in numbered_items if i.priority == "LOW"]

    counts = f"🔴{len(high)} High • 🟡{len(med)} Medium • 🟢{len(low)} Low"
    lines = [
        f"📋 *Action Plan* — {day_str}",
        f"*{len(numbered_items)} items:* {counts}",
        "━━━━━━━━━━━━━━━",
    ]
    if high:
        lines.append("🔴 *HIGH*")
        lines.extend(f"{n}. {i.subject}" for n, i in high)
        lines.append("━━━━━━━━━━━━━━━")
    if med:
        lines.append("🟡 *MEDIUM*")
        lines.extend(f"{n}. {i.subject}" for n, i in med)
        lines.append("━━━━━━━━━━━━━━━")
    if low:
        lines.append("🟢 *LOW*")
        lines.extend(f"{n}. {i.subject}" for n, i in low)
        lines.append("━━━━━━━━━━━━━━━")
    lines.append("_Reply 1 3 5 to mark done · /action for status_")

    message = "\n".join(lines)
    if len(message) > 1024:
        log.warning("whatsapp_message_long", chars=len(message))

    sid = None
    if s.WHATSAPP_ENABLED:
        sid = _send_whatsapp(message)
        log.info("whatsapp_dispatched", sid=sid, chars=len(message))

    return {"ok": True, "sid": sid, "char_count": len(message), "items": len(numbered_items)}


@router.post("/dispatch-delta")
async def whatsapp_dispatch_delta(payload: DispatchPayload) -> dict:
    """Hourly delta: append items, continue numbering."""
    s = get_settings()
    pool = _require_pool()
    today = _today_ist()
    now_str = _format_time_12h(_ist_now())

    async with pool.acquire() as conn:
        start_num = await _next_number_for_today(conn, today)

        numbered_items: list[tuple[int, ActionItem]] = []
        for idx, item in enumerate(payload.items):
            num = start_num + idx
            numbered_items.append((num, item))
            await conn.execute(
                """
                INSERT INTO crux_action_items (
                    plan_date, number, priority, subject, from_email, status
                )
                VALUES ($1, $2, $3, $4, $5, 'pending')
                ON CONFLICT (plan_date, number) DO NOTHING
                """,
                today,
                num,
                item.priority,
                item.subject,
                item.from_email or None,
            )

        await conn.execute(
            """
            INSERT INTO crux_daily_runs (plan_date, run_type, new_item_count, whatsapp_sent)
            VALUES ($1, 'hourly', $2, $3)
            """,
            today,
            len(payload.items),
            s.WHATSAPP_ENABLED,
        )

    high = [(n, i) for n, i in numbered_items if i.priority == "HIGH"]
    med = [(n, i) for n, i in numbered_items if i.priority == "MEDIUM"]

    noun = "items" if len(numbered_items) != 1 else "item"
    lines = [
        f"🔔 *{len(numbered_items)} new {noun}* — {now_str} update",
        "━━━━━━━━━━━━━━━",
    ]
    if high:
        lines.append("🔴 *HIGH*")
        lines.extend(f"{n}. {i.subject}" for n, i in high)
        lines.append("━━━━━━━━━━━━━━━")
    if med:
        lines.append("🟡 *MEDIUM*")
        lines.extend(f"{n}. {i.subject}" for n, i in med)
        lines.append("━━━━━━━━━━━━━━━")
    lines.append("_Reply numbers to mark done · /action for full status_")

    message = "\n".join(lines)
    sid = None
    if s.WHATSAPP_ENABLED:
        sid = _send_whatsapp(message)

    return {"ok": True, "sid": sid, "char_count": len(message)}


@router.post("/dispatch-summary")
async def whatsapp_dispatch_summary() -> dict:
    """7 PM IST summary via n8n cron."""
    s = get_settings()
    pool = _require_pool()
    today = _today_ist()

    async with pool.acquire() as conn:
        items = await _get_today_items(conn, today)
        await conn.execute(
            """
            INSERT INTO crux_daily_runs (plan_date, run_type, item_count, whatsapp_sent)
            VALUES ($1, 'evening', $2, $3)
            """,
            today,
            len(items),
            s.WHATSAPP_ENABLED,
        )

    if not items:
        return {"ok": True, "message": "No items today"}

    message = _build_summary_message(items, today)
    sid = None
    if s.WHATSAPP_ENABLED:
        sid = _send_whatsapp(message)

    return {"ok": True, "sid": sid, "char_count": len(message)}


@router.get("/action/today")
async def action_today() -> dict:
    pool = _require_pool()
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


@router.post("/action/mark-done")
async def action_mark_done(req: MarkDoneRequest) -> dict:
    pool = _require_pool()
    today = _today_ist()
    now = _ist_now()

    async with pool.acquire() as conn:
        updated: list[int] = []
        for num in req.numbers:
            result = await conn.execute(
                """
                UPDATE crux_action_items
                SET status = 'done', done_at = $1
                WHERE plan_date = $2 AND number = $3 AND status = 'pending'
                """,
                now,
                today,
                num,
            )
            if result != "UPDATE 0":
                updated.append(num)

    if updated:
        nums = ", ".join(str(n) for n in updated)
        reply = f"✅ Marked done: {nums}"
    else:
        reply = "⚠️ No matching pending items found"

    return {"ok": True, "updated": updated, "reply_message": reply}


@router.get("/action/delta")
async def action_delta() -> dict:
    pool = _require_pool()
    today = _today_ist()

    async with pool.acquire() as conn:
        last_run = await conn.fetchrow(
            """
            SELECT run_at FROM crux_daily_runs
            WHERE plan_date = $1 AND run_type IN ('morning', 'hourly')
            ORDER BY run_at DESC LIMIT 1
            """,
            today,
        )
        last_run_at = last_run["run_at"] if last_run else None

        if last_run_at:
            new_rows = await conn.fetch(
                """
                SELECT number, priority, subject, status, done_at
                FROM crux_action_items
                WHERE plan_date = $1 AND created_at > $2
                ORDER BY number
                """,
                today,
                last_run_at,
            )
        else:
            new_rows = []

        next_num = await _next_number_for_today(conn, today)

    row_dicts = [dict(r) for r in new_rows]
    return DeltaResponse(
        has_new_items=len(row_dicts) > 0,
        has_high=any(i["priority"] == "HIGH" for i in row_dicts),
        has_medium=any(i["priority"] == "MEDIUM" for i in row_dicts),
        new_items=[ActionStatusItem.model_validate(i) for i in row_dicts],
        next_number=next_num,
    ).model_dump()


@router.get("/inbound", response_class=PlainTextResponse)
async def whatsapp_inbound_probe() -> PlainTextResponse:
    """Tunnel or path check: open this URL in a browser or curl GET. Twilio sends POST only."""
    return PlainTextResponse(
        "Crux WhatsApp webhook OK. Twilio must POST to this same path with form "
        "fields Body and From. If you use ngrok free and see errors or HTML, append "
        "query ngrok-skip-browser-warning equals true to the webhook URL in Twilio."
    )


async def _handle_whatsapp_inbound(body_text: str, from_addr: str) -> PlainTextResponse:
    log.debug("whatsapp_inbound", from_addr=from_addr)
    body = body_text.strip()
    pool = _require_pool()
    today = _today_ist()

    if body.lower() == "/action":
        async with pool.acquire() as conn:
            items = await _get_today_items(conn, today)
        reply = _build_status_message(items, today)

    elif (numbers := _parse_mark_done_numbers(body)) is not None:
        async with pool.acquire() as conn:
            updated: list[int] = []
            for num in numbers:
                result = await conn.execute(
                    """
                    UPDATE crux_action_items
                    SET status = 'done', done_at = NOW()
                    WHERE plan_date = $1 AND number = $2 AND status = 'pending'
                    """,
                    today,
                    num,
                )
                if result != "UPDATE 0":
                    updated.append(num)
        if updated:
            async with pool.acquire() as conn:
                items = await _get_today_items(conn, today)
            reply = _build_status_message(items, today)
        else:
            reply = "⚠️ No matching pending items"
    else:
        return PlainTextResponse(
            "<?xml version='1.0'?><Response></Response>",
            media_type="application/xml",
        )

    safe = html.escape(reply, quote=False)
    twiml = f"""<?xml version='1.0'?>
<Response>
  <Message>{safe}</Message>
</Response>"""
    return PlainTextResponse(twiml, media_type="application/xml")


@router.post("/inbound", response_class=PlainTextResponse)
async def whatsapp_inbound(
    body_text: str = Form("", alias="Body"),
    from_addr: str = Form("", alias="From"),
) -> PlainTextResponse:
    """Twilio webhook: TwiML reply. Same path as GET probe; Twilio uses POST only."""
    return await _handle_whatsapp_inbound(body_text, from_addr)


@router.get("/status")
async def whatsapp_status() -> dict:
    s = get_settings()
    pool = _require_pool()
    today = _today_ist()

    async with pool.acquire() as conn:
        items = await _get_today_items(conn, today)
        runs = await conn.fetch(
            """
            SELECT run_type, run_at, item_count, whatsapp_sent
            FROM crux_daily_runs WHERE plan_date = $1 ORDER BY run_at
            """,
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
