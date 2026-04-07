from __future__ import annotations

import structlog

from server.config import CruxSettings, get_settings
from server.llm.cache import (
    exact_cache_get,
    exact_cache_set,
    persist_generation,
    prompt_fingerprint,
    semantic_cache_lookup,
)
from server.llm.claude_client import chat_claude
from server.llm.openrouter_client import chat_openrouter, embed_openrouter

log = structlog.get_logger(__name__)


async def chat(
    prompt: str,
    system: str = "",
    source: str | None = None,
    *,
    settings: CruxSettings | None = None,
) -> dict:
    settings = settings or get_settings()
    model_key = settings.OPENROUTER_MODEL
    sys_fp = prompt_fingerprint(system, "")

    hit = await exact_cache_get(model_key, system, prompt)
    if hit:
        await persist_generation(
            prompt_hash=prompt_fingerprint(system, prompt),
            prompt_text=prompt,
            system_fingerprint=sys_fp,
            response_text=hit,
            model=model_key,
            provider="cache",
            source=source,
            embedding=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=0,
            cached=True,
            cache_hit_type="exact",
            metadata={"model_key": model_key},
            settings=settings,
        )
        return {"response": hit, "cached": True, "cache_hit_type": "exact"}

    emb: list[float] | None = None
    if settings.CRUX_SEMANTIC_CACHE_ENABLED and settings.OPENROUTER_API_KEY:
        try:
            emb = await embed_openrouter(f"{system}\n{prompt}", settings=settings)
            sem = await semantic_cache_lookup(emb, model_key, settings=settings)
            if sem:
                text, _sim = sem
                await persist_generation(
                    prompt_hash=prompt_fingerprint(system, prompt),
                    prompt_text=prompt,
                    system_fingerprint=sys_fp,
                    response_text=text,
                    model=model_key,
                    provider="cache",
                    source=source,
                    embedding=emb,
                    input_tokens=None,
                    output_tokens=None,
                    latency_ms=0,
                    cached=True,
                    cache_hit_type="semantic",
                    metadata={"model_key": model_key},
                    settings=settings,
                )
                return {"response": text, "cached": True, "cache_hit_type": "semantic"}
        except Exception as e:
            log.warning("semantic_cache_embed_lookup_failed", err=str(e))
            emb = None

    text: str
    model: str
    it: int | None
    ot: int | None
    lat: int
    provider: str

    prov = settings.CRUX_LLM_PROVIDER.lower().strip()
    if prov == "claude" and settings.CLAUDE_ENABLED and settings.ANTHROPIC_API_KEY:
        text, model, it, ot, lat = await chat_claude(prompt, system, settings=settings)
        provider = "anthropic"
    elif prov == "auto":
        try:
            text, model, it, ot, lat = await chat_openrouter(prompt, system, settings=settings)
            provider = "openrouter"
        except Exception:
            text, model, it, ot, lat = await chat_claude(prompt, system, settings=settings)
            provider = "anthropic"
    else:
        text, model, it, ot, lat = await chat_openrouter(prompt, system, settings=settings)
        provider = "openrouter"

    if emb is None and settings.CRUX_SEMANTIC_CACHE_ENABLED and settings.OPENROUTER_API_KEY:
        try:
            emb = await embed_openrouter(f"{system}\n{prompt}", settings=settings)
        except Exception as e:
            log.warning("embed_for_persist_failed", err=str(e))
            emb = None

    await persist_generation(
        prompt_hash=prompt_fingerprint(system, prompt),
        prompt_text=prompt,
        system_fingerprint=sys_fp,
        response_text=text,
        model=model,
        provider=provider,
        source=source,
        embedding=emb,
        input_tokens=it,
        output_tokens=ot,
        latency_ms=lat,
        cached=False,
        cache_hit_type=None,
        metadata={"model_key": model_key},
        settings=settings,
    )
    await exact_cache_set(model_key, system, prompt, text)
    return {"response": text, "cached": False, "cache_hit_type": None}
