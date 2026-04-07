from __future__ import annotations

import time

import structlog
from openai import AsyncOpenAI

from server.config import CruxSettings, get_settings

log = structlog.get_logger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


async def chat_openrouter(
    prompt: str,
    system: str,
    *,
    settings: CruxSettings | None = None,
) -> tuple[str, str, int | None, int | None, int]:
    settings = settings or get_settings()
    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set")

    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE,
    )
    model = settings.OPENROUTER_MODEL
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as e:
        log.warning("openrouter_primary_failed", err=str(e))
        model = settings.OPENROUTER_FALLBACK_MODEL
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            )
        except Exception as e2:
            raise e2 from e

    latency_ms = int((time.perf_counter() - t0) * 1000)
    choice = resp.choices[0]
    text = (choice.message.content or "").strip()
    u = getattr(resp, "usage", None)
    it = getattr(u, "prompt_tokens", None) if u else None
    ot = getattr(u, "completion_tokens", None) if u else None
    return text, model, it, ot, latency_ms


async def embed_openrouter(
    text: str,
    *,
    settings: CruxSettings | None = None,
) -> list[float]:
    settings = settings or get_settings()
    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not set")
    client = AsyncOpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=OPENROUTER_BASE,
    )
    resp = await client.embeddings.create(
        model=settings.OPENROUTER_EMBEDDING_MODEL,
        input=text[:8000],
    )
    return list(resp.data[0].embedding)
