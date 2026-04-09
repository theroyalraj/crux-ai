#!/usr/bin/env python3
"""Manual check: same Twilio REST path as production inbound (Messages.create + media_url).

Inbound webhook uses this pattern internally after computing reply text.

Run: PYTHONPATH=. python scripts/verify_twilio_whatsapp_media.py
"""

from __future__ import annotations

import re
import sys

import httpx
from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from server.config import get_settings


def main() -> int:
    s = get_settings()
    base = (s.CRUX_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if not base:
        print("error: set CRUX_PUBLIC_BASE_URL (HTTPS, e.g. ngrok)", file=sys.stderr)
        return 1

    sid = (s.WHATSAPP_ACCOUNT_SID or "").strip()
    token = (s.WHATSAPP_AUTH_TOKEN or "").strip()
    if not sid or not token:
        print("error: WHATSAPP_ACCOUNT_SID and WHATSAPP_AUTH_TOKEN required", file=sys.stderr)
        return 1

    port = int(s.CRUX_PORT)
    bind = (s.CRUX_HOST or "127.0.0.1").strip()
    # httpx cannot connect to 0.0.0.0; use loopback for local Crux.
    host = "127.0.0.1" if bind in ("0.0.0.0", "::", "[::]") else bind
    local = f"http://{host}:{port}"
    inbound = f"{local}/whatsapp/inbound"

    with httpx.Client(timeout=120.0) as http:
        r = http.post(
            inbound,
            data={
                "Body": "perfect",
                "From": (s.WHATSAPP_TO or "whatsapp:+10000000000").strip(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    r.raise_for_status()
    m = re.search(r"<Media>(https?://[^<]+)</Media>", r.text)
    if not m:
        print("error: no <Media> in TwiML:\n", r.text[:800], file=sys.stderr)
        return 1
    media_url = m.group(1).strip()
    print("media_url:", media_url)

    client = Client(sid, token)
    try:
        msg = client.messages.create(
            body="Twilio API test: text plus MP3 from Crux /whatsapp/media.",
            from_=s.WHATSAPP_FROM.strip(),
            to=s.WHATSAPP_TO.strip(),
            media_url=[media_url],
        )
    except TwilioRestException as e:
        print("TwilioRestException:", e.status, e.msg, e.code, file=sys.stderr)
        if e.details:
            print("details:", e.details, file=sys.stderr)
        return 2

    print("ok sid:", msg.sid, "status:", msg.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
