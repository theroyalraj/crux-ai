from __future__ import annotations

import httpx
import structlog

from server.config import get_settings
from server.voice.eleven_tls import eleven_httpx_verify

log = structlog.get_logger(__name__)


async def fetch_convai_signed_url(*, agent_id: str) -> str:
    """GET /v1/convai/conversation/get-signed-url — returns wss URL for @elevenlabs/client."""
    s = get_settings()
    key = (s.CRUX_ELEVENLABS_API_KEY or "").strip()
    if not key:
        raise RuntimeError("CRUX_ELEVENLABS_API_KEY is not set")

    aid = (agent_id or "").strip() or (s.CRUX_ELEVENLABS_AGENT_ID or "").strip()
    if not aid:
        raise RuntimeError("agent_id missing and CRUX_ELEVENLABS_AGENT_ID is not set")

    base = (s.CRUX_ELEVENLABS_BASE_URL or "https://api.elevenlabs.io").rstrip("/")
    url = f"{base}/v1/convai/conversation/get-signed-url"
    verify = eleven_httpx_verify(s)
    timeout = s.CRUX_ELEVENLABS_TIMEOUT_SEC
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
            resp = await client.get(
                url,
                params={"agent_id": aid},
                headers={"xi-api-key": key},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        log.warning("convai_signed_url_failed", err=str(e))
        raise

    signed = data.get("signed_url") or data.get("signedUrl")
    if not signed or not isinstance(signed, str):
        raise RuntimeError("ConvAI response missing signed_url")
    return signed.strip()
