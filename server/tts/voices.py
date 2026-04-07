from __future__ import annotations

from server.config import CruxSettings, get_settings


def blocked_voices(settings: CruxSettings | None = None) -> set[str]:
    settings = settings or get_settings()
    return {v.strip() for v in settings.CRUX_TTS_VOICE_BLOCK.split(",") if v.strip()}


def resolve_edge_voice(requested: str, settings: CruxSettings | None = None) -> str:
    settings = settings or get_settings()
    blocked = blocked_voices(settings)
    v = (requested or settings.CRUX_TTS_VOICE).strip() or settings.CRUX_TTS_VOICE
    if v in blocked:
        if settings.CRUX_TTS_VOICE not in blocked:
            return settings.CRUX_TTS_VOICE
        return "en-US-GuyNeural"
    return v


def _say_blocked(settings: CruxSettings) -> set[str]:
    return {v.strip() for v in settings.CRUX_SAY_VOICE_BLOCK.split(",") if v.strip()}


def resolve_say_voice(requested: str, settings: CruxSettings | None = None) -> str:
    settings = settings or get_settings()
    blocked = _say_blocked(settings)
    d = (settings.CRUX_SAY_VOICE_DEFAULT or "Samantha").strip() or "Samantha"
    v = (requested or d).strip() or d
    if v in blocked:
        return d if d not in blocked else "Alex"
    return v


# Rachel: multilingual-friendly default in ElevenLabs voice library
_DEFAULT_ELEVEN_VOICE = "21m00Tcm4TlvDq8ikWAM"


def _eleven_blocked(settings: CruxSettings) -> set[str]:
    return {v.strip() for v in settings.CRUX_ELEVENLABS_VOICE_BLOCK.split(",") if v.strip()}


def resolve_eleven_voice_id(requested: str, settings: CruxSettings | None = None) -> str:
    settings = settings or get_settings()
    blocked = _eleven_blocked(settings)
    env_default = (settings.CRUX_ELEVENLABS_VOICE_ID or "").strip()
    fallback = env_default or _DEFAULT_ELEVEN_VOICE
    v = (requested or env_default or _DEFAULT_ELEVEN_VOICE).strip() or fallback
    if v in blocked:
        return fallback if fallback not in blocked else _DEFAULT_ELEVEN_VOICE
    return v
