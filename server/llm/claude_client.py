from __future__ import annotations

import time

import structlog
from anthropic import AsyncAnthropic

from server.config import CruxSettings, get_settings

log = structlog.get_logger(__name__)


async def chat_claude(
    prompt: str,
    system: str,
    *,
    settings: CruxSettings | None = None,
) -> tuple[str, str, int | None, int | None, int]:
    settings = settings or get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not set")

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    model = settings.CLAUDE_MODEL
    t0 = time.perf_counter()
    msg = await client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    parts = []
    for b in msg.content:
        if hasattr(b, "text"):
            parts.append(b.text)
    text = "".join(parts).strip()
    it = getattr(msg.usage, "input_tokens", None)
    ot = getattr(msg.usage, "output_tokens", None)
    return text, model, it, ot, latency_ms
