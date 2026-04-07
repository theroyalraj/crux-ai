from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Persona:
    """Runtime persona metadata. TTS voices/locales live in `server/tts/data/tts_registry.json`."""

    key: str
    name: str
    title: str
    actions: frozenset[str]


PERSONAS: dict[str, Persona] = {
    "forge": Persona(
        key="forge",
        name="Forge",
        title="Chief Architect",
        actions=frozenset(
            {"acknowledge", "narrate", "completion", "general"},
        ),
    ),
    "sentinel": Persona(
        key="sentinel",
        name="Sentinel",
        title="Code Guardian",
        actions=frozenset({"review", "security_scan", "pre_commit"}),
    ),
    "chronicle": Persona(
        key="chronicle",
        name="Chronicle",
        title="Release Engineer",
        actions=frozenset({"commit", "mr", "hourly_checkpoint", "changelog"}),
    ),
    "sage": Persona(
        key="sage",
        name="Sage",
        title="Research Analyst",
        actions=frozenset({"thinking", "analysis", "explanation"}),
    ),
    "maestro": Persona(
        key="maestro",
        name="Maestro",
        title="Operations Lead",
        actions=frozenset({"ambient", "break_reminder", "hydration", "posture"}),
    ),
    "echo": Persona(
        key="echo",
        name="Echo",
        title="Context Keeper",
        actions=frozenset({"file_watch", "transcript", "context_update"}),
    ),
    "siri": Persona(
        key="siri",
        name="Siri",
        title="System Assistant",
        actions=frozenset({"voice_assistant", "general"}),
    ),
}


def default_persona_key() -> str:
    return "forge"
