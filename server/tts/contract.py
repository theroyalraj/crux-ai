from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TtsPlaybackRequest:
    """Normalized text + voice parameters for all built-in providers (each uses its subset)."""

    text: str
    edge_voice: str
    edge_rate: str
    edge_pitch: str
    say_voice: str
    say_wpm: int
    stream: bool
    eleven_voice_id: str
    eleven_model_id: str
    eleven_output_format: str
    # Resolved persona key for relay JSON (e.g. forge); optional for backwards compatibility.
    persona: str | None = None
