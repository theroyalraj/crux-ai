from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from server.config import CruxSettings, get_settings
from server.personas.registry import default_persona_key
from server.tts.config_loader import effective_provider_chain, load_merged_registry
from server.tts.contract import TtsPlaybackRequest
from server.tts.eleven_models import resolve_eleven_model_id
from server.tts.engine import normalize_for_speech
from server.tts.providers.base import TtsProvider
from server.tts.providers.edge_provider import EdgeTtsProvider
from server.tts.providers.elevenlabs_provider import ElevenLabsTtsProvider
from server.tts.providers.relay_provider import RelayTtsProvider
from server.tts.providers.say_provider import MacSayProvider
from server.tts.voices import resolve_edge_voice, resolve_eleven_voice_id, resolve_say_voice

log = structlog.get_logger(__name__)


def _clamp_wpm(n: int) -> int:
    return max(50, min(500, n))


def _merge_locale_voices(
    cfg: dict[str, Any],
    persona_key: str,
    settings: CruxSettings,
) -> tuple[str, dict[str, Any], list[str], str] | None:
    pk = (persona_key or default_persona_key()).lower().strip()
    default_loc = cfg.get("default_locale", "en-US")
    personas = cfg.get("personas", {})
    p_entry = personas.get(pk, {})
    locale = p_entry.get("locale", default_loc)
    locales = cfg.get("locales", {})
    if locale not in locales:
        log.error("tts_unknown_locale", locale=locale, persona=pk)
        return None
    loc = locales[locale]
    voices = copy.deepcopy(loc.get("voices", {}))
    overrides = p_entry.get("overrides", {})
    for prov, patch in overrides.items():
        if prov not in voices:
            voices[prov] = {}
        if isinstance(voices[prov], dict) and isinstance(patch, dict):
            voices[prov] = {**voices[prov], **patch}
    chain = list(loc.get("chain", []))
    chain = effective_provider_chain(cfg, chain, settings)
    if not chain:
        log.error("tts_empty_chain", locale=locale, persona=pk)
        return None
    return locale, voices, chain, pk


def _build_request(
    text: str,
    voices: dict[str, Any],
    stream: bool,
    settings: CruxSettings,
    *,
    persona_key: str | None,
) -> TtsPlaybackRequest:
    edge = voices.get("edge", {}) if isinstance(voices.get("edge"), dict) else {}
    say = voices.get("say", {}) if isinstance(voices.get("say"), dict) else {}
    ev = resolve_edge_voice(str(edge.get("voice", settings.CRUX_TTS_VOICE)), settings)
    er = str(edge.get("rate", settings.CRUX_TTS_RATE))
    ep = str(edge.get("pitch", settings.CRUX_TTS_PITCH))
    sv = resolve_say_voice(str(say.get("voice", settings.CRUX_SAY_VOICE_DEFAULT)), settings)
    base_wpm = int(say.get("wpm", settings.CRUX_SAY_RATE_WPM))
    delta = int(say.get("wpm_delta", 0))
    wpm = _clamp_wpm(base_wpm + delta)
    eleven = voices.get("eleven", {}) if isinstance(voices.get("eleven"), dict) else {}
    e_vid = resolve_eleven_voice_id(str(eleven.get("voice_id", "")), settings)
    e_model = resolve_eleven_model_id(
        settings.CRUX_ELEVENLABS_MODEL_TIER,
        str(eleven.get("model_id", "")).strip() or None,
    )
    e_fmt = str(eleven.get("output_format", settings.CRUX_ELEVENLABS_OUTPUT_FORMAT)).strip()
    return TtsPlaybackRequest(
        text=text,
        edge_voice=ev,
        edge_rate=er,
        edge_pitch=ep,
        say_voice=sv,
        say_wpm=wpm,
        stream=stream,
        eleven_voice_id=e_vid,
        eleven_model_id=e_model,
        eleven_output_format=e_fmt or settings.CRUX_ELEVENLABS_OUTPUT_FORMAT,
        persona=persona_key,
    )


class TtsService:
    """Selects a TTS provider from JSON registry + platform rules and runs playback."""

    def __init__(self, settings: CruxSettings, registry: dict[str, Any]) -> None:
        self._settings = settings
        self._registry = registry
        self._providers: dict[str, TtsProvider] = {
            "eleven": ElevenLabsTtsProvider(),
            "say": MacSayProvider(),
            "edge": EdgeTtsProvider(),
            "relay": RelayTtsProvider(),
        }

    def register_provider(self, provider: TtsProvider) -> None:
        self._providers[provider.id] = provider

    async def speak(
        self,
        text: str,
        *,
        persona: str | None,
        stream: bool,
        generation_ok: Callable[[], bool | Awaitable[bool]],
    ) -> float:
        merged = _merge_locale_voices(self._registry, persona or "", self._settings)
        if merged is None:
            return 0.0
        _locale, voices, chain, pk = merged
        clean = normalize_for_speech(text)
        req = _build_request(clean, voices, stream, self._settings, persona_key=pk)

        last_err: BaseException | None = None
        for pid in chain:
            prov = self._providers.get(pid)
            if prov is None:
                log.warning("tts_unknown_provider_id", id=pid)
                continue
            if not prov.is_available():
                log.debug("tts_provider_skip_unavailable", provider=pid)
                continue
            try:
                log.info("tts_using_provider", provider=pid, locale=_locale)
                return await prov.speak(req, generation_ok)
            except Exception as e:
                last_err = e
                log.warning("tts_provider_failed_try_next", provider=pid, err=str(e))
        if last_err:
            log.error("tts_all_providers_failed", err=str(last_err))
        else:
            log.error("tts_no_available_provider", chain=chain)
        return 0.0

    async def synthesize_mp3(self, text: str, *, persona: str | None) -> tuple[bytes, str] | None:
        """Return (mp3_bytes, provider_id) for HTTP synthesize; no playback, no speaker lock."""
        merged = _merge_locale_voices(self._registry, persona or "", self._settings)
        if merged is None:
            return None
        _locale, voices, chain, pk = merged
        clean = normalize_for_speech(text)
        req = _build_request(clean, voices, stream=False, settings=self._settings, persona_key=pk)
        synth_chain = [p for p in chain if p in ("eleven", "edge")]
        last_err: BaseException | None = None
        for pid in synth_chain:
            prov = self._providers.get(pid)
            if prov is None:
                continue
            sm = getattr(prov, "synthesize_mp3", None)
            if sm is None or not callable(sm):
                continue
            if not prov.is_available():
                log.debug("tts_synth_skip_unavailable", provider=pid)
                continue
            try:
                log.info("tts_synthesize_using", provider=pid, locale=_locale)
                out = await sm(req)
                if out:
                    return out, pid
            except Exception as e:
                last_err = e
                log.warning("tts_synthesize_failed_try_next", provider=pid, err=str(e))
        if last_err:
            log.error("tts_synthesize_all_failed", err=str(last_err))
        else:
            log.error("tts_synthesize_no_provider", chain=synth_chain)
        return None


_tts_service: TtsService | None = None


def get_tts_service() -> TtsService:
    global _tts_service
    if _tts_service is None:
        s = get_settings()
        reg = load_merged_registry(s)
        _tts_service = TtsService(s, reg)
    return _tts_service


def reset_tts_service_for_tests() -> None:
    global _tts_service
    _tts_service = None
