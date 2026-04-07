from __future__ import annotations

# ElevenLabs model_id values (API). Tier names are Crux config CRUX_ELEVENLABS_MODEL_TIER.
ELEVEN_MODEL_BY_TIER: dict[str, str] = {
    "basic": "eleven_flash_v2_5",
    "medium": "eleven_turbo_v2_5",
    "best": "eleven_multilingual_v2",
}


def resolve_eleven_model_id(tier: str, registry_override: str | None) -> str:
    if registry_override and str(registry_override).strip():
        return str(registry_override).strip()
    key = (tier or "basic").strip().lower()
    return ELEVEN_MODEL_BY_TIER.get(key, ELEVEN_MODEL_BY_TIER["basic"])
