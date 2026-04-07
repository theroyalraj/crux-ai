from __future__ import annotations

import copy
import importlib.resources as ir
import json
import sys
from pathlib import Path
from typing import Any

import structlog

from server.config import CruxSettings

log = structlog.get_logger(__name__)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_bundled_registry() -> dict[str, Any]:
    try:
        raw = ir.files("server.tts.data").joinpath("tts_registry.json").read_text(encoding="utf-8")
    except (ModuleNotFoundError, OSError, TypeError, FileNotFoundError):
        fb = Path(__file__).resolve().parent / "data" / "tts_registry.json"
        raw = fb.read_text(encoding="utf-8")
    return json.loads(raw)


def load_user_overlay(path: str) -> dict[str, Any]:
    p = Path(path).expanduser()
    if not p.is_file():
        log.warning("tts_config_path_missing", path=str(p))
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def load_merged_registry(settings: CruxSettings) -> dict[str, Any]:
    cfg = load_bundled_registry()
    extra = (settings.CRUX_TTS_CONFIG_PATH or "").strip()
    if extra:
        cfg = deep_merge(cfg, load_user_overlay(extra))
    apply_env_voice_overrides(cfg, settings)
    return cfg


def apply_env_voice_overrides(cfg: dict[str, Any], s: CruxSettings) -> None:
    """Legacy .env voice overrides → merge into persona overrides."""
    mapping = [
        ("forge", s.CRUX_FORGE_VOICE, s.CRUX_FORGE_RATE, s.CRUX_FORGE_SAY_VOICE),
        ("sentinel", s.CRUX_SENTINEL_VOICE, s.CRUX_SENTINEL_RATE, s.CRUX_SENTINEL_SAY_VOICE),
        ("chronicle", s.CRUX_CHRONICLE_VOICE, s.CRUX_CHRONICLE_RATE, s.CRUX_CHRONICLE_SAY_VOICE),
        ("sage", s.CRUX_SAGE_VOICE, s.CRUX_SAGE_RATE, s.CRUX_SAGE_SAY_VOICE),
        ("maestro", s.CRUX_MAESTRO_VOICE, s.CRUX_MAESTRO_RATE, s.CRUX_MAESTRO_SAY_VOICE),
        ("echo", s.CRUX_ECHO_VOICE, s.CRUX_ECHO_RATE, s.CRUX_ECHO_SAY_VOICE),
    ]
    cfg.setdefault("personas", {})
    for key, ev, er, sv in mapping:
        if not any((ev, er, sv)):
            continue
        cfg["personas"].setdefault(key, {})
        cfg["personas"][key].setdefault("overrides", {})
        o = cfg["personas"][key]["overrides"]
        if ev.strip():
            o.setdefault("edge", {})["voice"] = ev.strip()
        if er.strip():
            o.setdefault("edge", {})["rate"] = er.strip()
        if sv.strip():
            o.setdefault("say", {})["voice"] = sv.strip()


def effective_provider_chain(
    cfg: dict[str, Any],
    locale_chain: list[str],
    settings: CruxSettings,
) -> list[str]:
    plat = sys.platform
    allowed = list(cfg.get("platform_chains", {}).get(plat, ["edge"]))
    if not settings.CRUX_EDGE_TTS_ENABLED:
        allowed = [p for p in allowed if p != "edge"]
    if plat != "darwin":
        allowed = [p for p in allowed if p != "say"]
    if not settings.CRUX_ELEVENLABS_ENABLED or not (settings.CRUX_ELEVENLABS_API_KEY or "").strip():
        allowed = [p for p in allowed if p != "eleven"]

    chain = [p for p in locale_chain if p in allowed]

    forced = (settings.CRUX_TTS_PROVIDER or "").strip().lower()
    if forced in ("say", "edge", "eleven"):
        filtered = [p for p in chain if p == forced]
        if not filtered:
            log.warning(
                "tts_forced_provider_unavailable_for_locale",
                forced=forced,
                chain=chain,
            )
            return chain
        return filtered

    return chain
