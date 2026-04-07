from __future__ import annotations

import hashlib
import json
from typing import Any

import structlog

from server.config import CruxSettings, get_settings
from server.db.postgres import get_pool
from server.db.redis_client import get_redis

log = structlog.get_logger(__name__)


def _exact_key(model_key: str, system: str, prompt: str) -> str:
    h = hashlib.sha256(f"{model_key}|{system}|{prompt}".encode()).hexdigest()
    return f"crux:llm:exact:{h}"


async def exact_cache_get(model_key: str, system: str, prompt: str) -> str | None:
    settings = get_settings()
    if not settings.CRUX_EXACT_CACHE_ENABLED:
        return None
    r = get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(_exact_key(model_key, system, prompt))
        if raw:
            return str(raw)
    except Exception as e:
        log.warning("exact_cache_get_failed", err=str(e))
    return None


async def exact_cache_set(model_key: str, system: str, prompt: str, response: str) -> None:
    settings = get_settings()
    if not settings.CRUX_EXACT_CACHE_ENABLED:
        return
    r = get_redis()
    if r is None:
        return
    try:
        await r.set(
            _exact_key(model_key, system, prompt),
            response,
            ex=settings.CACHE_TTL_SEC,
        )
    except Exception as e:
        log.warning("exact_cache_set_failed", err=str(e))


SEMANTIC_SQL = """
SELECT response_text,
       1 - (embedding <=> $1::vector) AS similarity
FROM ai_generation_log
WHERE (metadata->>'model_key') = $2
  AND created_at > NOW() - ($3::int * INTERVAL '1 day')
ORDER BY embedding <=> $1::vector
LIMIT 1
"""


async def semantic_cache_lookup(
    embedding: list[float],
    model_key: str,
    settings: CruxSettings | None = None,
) -> tuple[str, float] | None:
    settings = settings or get_settings()
    if not settings.CRUX_SEMANTIC_CACHE_ENABLED:
        return None
    pool = get_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                SEMANTIC_SQL,
                embedding,
                model_key,
                settings.CACHE_SEMANTIC_MAX_AGE_DAYS,
            )
        if not row:
            return None
        sim = float(row["similarity"])
        if sim >= settings.CACHE_SEMANTIC_THRESHOLD:
            return str(row["response_text"]), sim
    except Exception as e:
        log.warning("semantic_cache_lookup_failed", err=str(e))
    return None


async def persist_generation(
    *,
    prompt_hash: str,
    prompt_text: str,
    system_fingerprint: str,
    response_text: str,
    model: str,
    provider: str,
    source: str | None,
    embedding: list[float] | None,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int,
    cached: bool,
    cache_hit_type: str | None,
    metadata: dict[str, Any],
    settings: CruxSettings | None = None,
) -> None:
    settings = settings or get_settings()
    pool = get_pool()
    if pool is None:
        return
    meta = dict(metadata)
    meta["model_key"] = meta.get("model_key", model)
    try:
        async with pool.acquire() as conn:
            if embedding is None:
                await conn.execute(
                    """
                    INSERT INTO ai_generation_log (
                      prompt_hash, prompt_text, system_fingerprint, response_text,
                      model, provider, source, embedding, input_tokens, output_tokens,
                      latency_ms, cached, cache_hit_type, metadata
                    ) VALUES (
                      $1, $2, $3, $4, $5, $6, $7, NULL,
                      $8, $9, $10, $11, $12, $13::jsonb
                    )
                    """,
                    prompt_hash,
                    prompt_text[:50000],
                    system_fingerprint[:2000],
                    response_text[:500000],
                    model,
                    provider,
                    source,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    cached,
                    cache_hit_type,
                    json.dumps(meta),
                )
            else:
                await conn.execute(
                    """
                    INSERT INTO ai_generation_log (
                      prompt_hash, prompt_text, system_fingerprint, response_text,
                      model, provider, source, embedding, input_tokens, output_tokens,
                      latency_ms, cached, cache_hit_type, metadata
                    ) VALUES (
                      $1, $2, $3, $4, $5, $6, $7, $8::vector,
                      $9, $10, $11, $12, $13, $14::jsonb
                    )
                    """,
                    prompt_hash,
                    prompt_text[:50000],
                    system_fingerprint[:2000],
                    response_text[:500000],
                    model,
                    provider,
                    source,
                    embedding,
                    input_tokens,
                    output_tokens,
                    latency_ms,
                    cached,
                    cache_hit_type,
                    json.dumps(meta),
                )
    except Exception as e:
        log.warning("persist_generation_failed", err=str(e))


def prompt_fingerprint(system: str, prompt: str) -> str:
    return hashlib.sha256(f"{system}|{prompt}".encode()).hexdigest()[:32]
