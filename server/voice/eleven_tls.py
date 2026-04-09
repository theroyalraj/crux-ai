from __future__ import annotations

from server.config import CruxSettings


def eleven_httpx_verify(s: CruxSettings) -> bool | str:
    """Same TLS policy as ElevenLabs TTS provider."""
    if not s.CRUX_ELEVENLABS_VERIFY_TLS:
        return False
    ca = (s.CRUX_ELEVENLABS_SSL_CA_BUNDLE or "").strip()
    return ca if ca else True
