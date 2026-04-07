#!/usr/bin/env python3
"""Match a working curl call to ElevenLabs using the same httpx TLS rules as Crux.

Run from the repo root (no install required):

  PYTHONPATH=. python scripts/verify_elevenlabs_httpx.py

Uses CRUX_ELEVENLABS_API_KEY and optional CRUX_ELEVENLABS_BASE_URL, SSL bundle, and
verify flags from .env via server.config (same as the TTS provider).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from server.config import get_settings  # noqa: E402
from server.tts.providers.elevenlabs_provider import _eleven_httpx_verify  # noqa: E402
from server.tts.voices import resolve_eleven_voice_id  # noqa: E402

_DEFAULT_TEXT = "Hello from a direct Eleven Labs test."
_DEFAULT_MODEL = "eleven_flash_v2_5"
_DEFAULT_FORMAT = "mp3_44100_128"


def _looks_like_mp3_head(data: bytes) -> bool:
    if len(data) < 2:
        return False
    # ID3 tag or MPEG frame sync
    return data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)


async def run(*, text: str, voice_id: str) -> int:
    s = get_settings()
    key = (s.CRUX_ELEVENLABS_API_KEY or "").strip()
    if not key:
        print(
            "Missing CRUX_ELEVENLABS_API_KEY. Export it for this run or set it in .env.",
            file=sys.stderr,
        )
        return 2

    base = (s.CRUX_ELEVENLABS_BASE_URL or "https://api.elevenlabs.io").rstrip("/")
    url = f"{base}/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    body = {"text": text, "model_id": _DEFAULT_MODEL}
    params = {"output_format": _DEFAULT_FORMAT}
    verify = _eleven_httpx_verify(s)

    chunks: list[bytes] = []
    timeout = s.CRUX_ELEVENLABS_TIMEOUT_SEC
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=verify) as client:
            async with client.stream(
                "POST", url, headers=headers, json=body, params=params
            ) as resp:
                if resp.status_code >= 400:
                    raw = await resp.aread()
                    err = raw.decode("utf-8", errors="replace")[:800]
                    print(f"HTTP {resp.status_code}\n{err}", file=sys.stderr)
                    return 1
                resp.raise_for_status()
                async for part in resp.aiter_bytes():
                    if part:
                        chunks.append(part)
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        return 1

    audio = b"".join(chunks)
    if not audio:
        print("Empty response body.", file=sys.stderr)
        return 1

    head = audio[:16]
    ok = _looks_like_mp3_head(audio)
    print(f"OK received {len(audio)} bytes; first bytes look like MPEG: {ok}; verify={verify!r}")
    if not ok:
        print(f"Unexpected start (hex): {head.hex()}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Verify ElevenLabs over httpx like Crux TTS.")
    p.add_argument("--text", default=_DEFAULT_TEXT, help="Text to synthesize")
    p.add_argument(
        "--voice",
        default="",
        help="Voice id (default: resolve from env / registry default Rachel id)",
    )
    args = p.parse_args()
    s = get_settings()
    vid = (args.voice or "").strip() or resolve_eleven_voice_id("", s)
    code = asyncio.run(run(text=args.text, voice_id=vid))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
