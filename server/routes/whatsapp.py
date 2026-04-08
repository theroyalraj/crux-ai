from __future__ import annotations

import asyncio
import base64
import html
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
import structlog
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from server.config import get_settings
from server.db import get_pool
from server.db.redis_client import get_redis
from server.models.action import (
    ActionItem,
    ActionStatusItem,
    DeltaResponse,
    DispatchPayload,
    MarkDoneRequest,
)
from server.tts.service import get_tts_service

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


def _user_wants_voice(body: str) -> bool:
    """Voice attachment only when user explicitly asks (speak, talk to me, read aloud, …)."""
    low = body.lower().strip()
    if not low:
        return False
    patterns = (
        r"\bspeak\b",
        r"\btalk to me\b",
        r"\bvoice\b",
        r"\bnarrate\b",
        r"\btts\b",
        r"\b(read|say)\s+(it\s+)?(aloud|out loud)\b",
        r"\bread\s+(the\s+)?(message|plan|list|status|that)\b",
        r"\bsay\s+it\b",
        r"\bverbal(ly)?\b",
        r"\bas\s+audio\b",
        r"\bon\s+speaker\b",
    )
    return any(re.search(p, low) for p in patterns)


def _user_asks_action_plan(body: str) -> bool:
    """Natural-language requests for today's numbered status (same as /action)."""
    low = body.lower().strip()
    if not low or low == "/action":
        return False
    if "action plan" in low or "daily plan" in low:
        return True
    if re.search(r"\bmy\s+(action\s+)?plan\b", low):
        return True
    if re.search(
        r"\b(tell|show|give|send)\s+me\b.*\b(plan|tasks?|list|priorities|status|today)\b",
        low,
    ):
        return True
    if re.search(
        r"\b(tell|show|give|send)\s+(me\s+)?(the\s+)?(full\s+)?(plan|tasks|list|priorities|status)\b",
        low,
    ):
        return True
    if re.search(r"\bwhat\s+('?s|is)\s+(on\s+)?(my\s+)?(list|plate|schedule)\b", low):
        return True
    if re.search(r"\bwhat\s+(do\s+i\s+have|are\s+my\s+tasks|should\s+i\s+do)\b", low):
        return True
    if re.search(r"\b(remind\s+me|what\s+about)\b", low) and (
        "task" in low or "plan" in low or "today" in low
    ):
        return True
    if re.search(
        r"\b(full\s+status|my\s+tasks?|task\s+list|what'?s\s+on\s+my\s+list)\b",
        low,
    ):
        return True
    return False


def _fallback_reply_text(body: str) -> str:
    """When the message is not /action or mark-done numbers."""
    low = body.strip().lower()
    words = low.split()
    head = words[0] if words else ""
    positives = frozenset(
        {
            "perfect",
            "great",
            "awesome",
            "nice",
            "good",
            "super",
            "lovely",
            "excellent",
        }
    )
    if head in positives:
        return (
            "🙌 Noted — glad that works.\n"
            "Ask for your *action plan* or *my tasks*, or send /action. "
            "Reply with numbers (e.g. 8 done) to mark items. "
            "Say *speak* or *talk to me* if you want voice."
        )
    if low in ("ok", "k", "yes", "yep", "yeah", "thanks", "thank you", "thx"):
        return (
            "✅ Got it.\n"
            "Ask *what's my plan* or /action for your list. "
            "Numbers or *8 done* to mark done. Add *speak* for voice."
        )
    return (
        "👋 I can send your *action plan*, mark items by number, or chat in short replies.\n"
        "Try: *tell me my action plan*, *what do I have today*, or /action\n"
        "Mark done: *1 3* or *8 done*\n"
        "Voice (optional): add *speak* or *talk to me* to any request."
    )


def _public_base_url(request: Request) -> str | None:
    """Public HTTPS base for MP3 fetch: webhook host or CRUX_PUBLIC_BASE_URL."""
    s = get_settings()
    override = (s.CRUX_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if override:
        return override
    proto = (
        (request.headers.get("x-forwarded-proto") or request.url.scheme or "https")
        .split(",")[0]
        .strip()
    )
    host = (
        (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
        .split(",")[0]
        .strip()
    )
    if not host:
        return None
    return f"{proto}://{host}"


def _voice_script_from_reply(text: str, max_chars: int) -> str:
    """Strip markdown-ish noise for TTS; cap length."""
    t = re.sub(r"[*_~`#]", " ", text)
    t = re.sub(r"[━─—]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > max_chars:
        t = t[: max_chars - 3].rstrip() + "..."
    return t or "Update from your action plan."


async def _prepare_voice_media_url_for_text(
    request: Request, reply_text: str
) -> tuple[str | None, int]:
    """Public MP3 URL for Twilio media_url."""
    s = get_settings()
    if not s.CRUX_TTS_ENABLED or not s.WHATSAPP_VOICE_REPLY_ENABLED or not s.WHATSAPP_ENABLED:
        return None, 0

    base = _public_base_url(request)
    if not base:
        log.warning("whatsapp_voice_skip_no_public_base")
        return None, 0

    voice_text = _voice_script_from_reply(reply_text, s.WHATSAPP_VOICE_MAX_CHARS)
    persona = (s.WHATSAPP_VOICE_PERSONA or "").strip() or None
    try:
        svc = get_tts_service()
        synth = await svc.synthesize_mp3(voice_text, persona=persona)
    except Exception as e:
        log.warning("whatsapp_voice_synth_failed", err=str(e))
        return None, 0
    if not synth:
        return None, 0

    mp3, _prov = synth
    r = get_redis()
    if r is None:
        log.warning("whatsapp_voice_skip_no_redis")
        return None, 0

    media_id = secrets.token_urlsafe(24)
    try:
        await r.setex(
            f"crux:wa:media:{media_id}",
            s.WHATSAPP_MEDIA_TTL_SEC,
            base64.b64encode(mp3).decode("ascii"),
        )
    except Exception as e:
        log.warning("whatsapp_voice_redis_failed", err=str(e))
        return None, 0

    media_url = f"{base}/whatsapp/media/{media_id}"
    log.info("whatsapp_voice_media_ready", media_chars=len(voice_text), provider=_prov)
    return media_url, len(voice_text)


def _send_whatsapp_to_number(to: str, body: str, media_url: str | None) -> str:
    """Same pattern as scripts/verify_twilio_whatsapp_media.py: REST Messages.create."""
    s = get_settings()
    sid_ok = (s.WHATSAPP_ACCOUNT_SID or "").strip()
    tok_ok = (s.WHATSAPP_AUTH_TOKEN or "").strip()
    if not sid_ok or not tok_ok:
        raise RuntimeError("twilio_credentials_missing")
    if s.WHATSAPP_CONTENT_SID:
        raise RuntimeError("whatsapp_content_sid_blocks_freeform")
    client = _twilio_client()
    to = to.strip()
    from_ = s.WHATSAPP_FROM.strip()
    if media_url:
        msg = client.messages.create(
            body=body,
            from_=from_,
            to=to,
            media_url=[media_url],
        )
    else:
        msg = client.messages.create(body=body, from_=from_, to=to)
    return str(msg.sid)


def _twiml_message_only(reply_text: str) -> PlainTextResponse:
    safe = html.escape(reply_text, quote=False)
    twiml = f"<?xml version='1.0'?>\n<Response>\n  <Message>{safe}</Message>\n</Response>"
    return PlainTextResponse(twiml, media_type="application/xml")


def _twiml_empty() -> PlainTextResponse:
    """Webhook already replied via REST; Twilio expects valid TwiML."""
    return PlainTextResponse("<?xml version='1.0'?>\n<Response />\n", media_type="application/xml")


async def _deliver_inbound_reply(
    request: Request,
    reply_text: str,
    to_addr: str,
    *,
    voice_requested: bool = False,
) -> PlainTextResponse:
    """Twilio REST send; empty TwiML on success. Voice MP3 only if keywords or config allows."""
    s = get_settings()
    safe = html.escape(reply_text, quote=False)

    if not (s.WHATSAPP_ENABLED and (s.WHATSAPP_ACCOUNT_SID or "").strip() and to_addr.strip()):
        log.warning("whatsapp_inbound_skip_send", reason="disabled_or_no_to")
        return _twiml_message_only(reply_text)

    allow_voice = s.WHATSAPP_VOICE_REPLY_ENABLED and (
        not s.WHATSAPP_VOICE_KEYWORD_ONLY or voice_requested
    )
    media_url = None
    if allow_voice:
        media_url, _n = await _prepare_voice_media_url_for_text(request, reply_text)

    try:
        sid = await asyncio.to_thread(
            _send_whatsapp_to_number,
            to_addr,
            reply_text,
            media_url,
        )
        log.info("whatsapp_inbound_rest_sent", sid=sid, has_voice=bool(media_url))
        return _twiml_empty()
    except Exception as e:
        log.warning("whatsapp_inbound_rest_failed_fallback_twiml", err=str(e))
        if media_url:
            safe_url = html.escape(media_url, quote=True)
            twiml = f"""<?xml version='1.0'?>
<Response>
  <Message>
    <Body>{safe}</Body>
    <Media>{safe_url}</Media>
  </Message>
</Response>"""
            return PlainTextResponse(twiml, media_type="application/xml")
        return PlainTextResponse(
            f"<?xml version='1.0'?>\n<Response>\n  <Message>{safe}</Message>\n</Response>",
            media_type="application/xml",
        )


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


async def _handle_whatsapp_inbound(
    body_text: str, from_addr: str, request: Request
) -> PlainTextResponse:
    log.debug("whatsapp_inbound", from_addr=from_addr)
    body = body_text.strip()
    today = _today_ist()
    voice_requested = _user_wants_voice(body)

    bl = body.lower()
    if bl == "/action" or bl.startswith("/action "):
        pool = _require_pool()
        async with pool.acquire() as conn:
            items = await _get_today_items(conn, today)
        reply = _build_status_message(items, today)

    elif _user_asks_action_plan(body):
        pool = _require_pool()
        async with pool.acquire() as conn:
            items = await _get_today_items(conn, today)
        reply = _build_status_message(items, today)

    elif (numbers := _parse_mark_done_numbers(body)) is not None:
        pool = _require_pool()
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
        reply = _fallback_reply_text(body)

    return await _deliver_inbound_reply(request, reply, from_addr, voice_requested=voice_requested)


@router.post("/inbound", response_class=PlainTextResponse)
async def whatsapp_inbound(
    request: Request,
    body_text: str = Form("", alias="Body"),
    from_addr: str = Form("", alias="From"),
) -> PlainTextResponse:
    """Twilio webhook: TwiML reply. Same path as GET probe; Twilio uses POST only."""
    return await _handle_whatsapp_inbound(body_text, from_addr, request)


@router.get("/media/{media_id}")
async def whatsapp_media(media_id: str) -> Response:
    """Twilio GETs this URL to attach MP3 to the WhatsApp message."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,48}", media_id):
        raise HTTPException(status_code=404, detail="not found")
    r = get_redis()
    if r is None:
        raise HTTPException(status_code=503, detail="cache unavailable")
    raw = await r.get(f"crux:wa:media:{media_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="expired or missing")
    try:
        mp3 = base64.b64decode(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=404, detail="invalid") from None
    return Response(content=mp3, media_type="audio/mpeg")


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
