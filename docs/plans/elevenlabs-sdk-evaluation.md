# WIP checkpoint: ElevenLabs SDK vs current httpx TTS (WORK-123)

Saved as a branch checkpoint; no runtime code changes in this commit.

## Current state

- `server/tts/providers/elevenlabs_provider.py` calls the **Text-to-speech** HTTP API with **httpx** (stream, MP3), then plays via existing engine / cache.
- TLS is configurable via **`CRUX_ELEVENLABS_SSL_CA_BUNDLE`** and **`CRUX_ELEVENLABS_VERIFY_TLS`** (corporate proxy / macOS trust gaps vs curl or Postman).

## What the Eleven “agents” Python doc is

- [ElevenAgents Python SDK](https://elevenlabs.io/docs/eleven-agents/libraries/python) targets **interactive voice agents** (`Conversation`, `agent_id`, audio I/O). It is **not** a drop-in for Crux’s **one-shot string → audio** `/speak` path.

## Optional direction: official `elevenlabs` client for TTS only

If we adopt the PyPI **`elevenlabs`** package for **TTS** (not the conversational agent flow):

1. **Spike:** add dependency, call the documented TTS/stream API from the client (if it exposes bytes or a stream compatible with our cache + ffplay).
2. **Wire:** keep `TtsPlaybackRequest`, Redis cache keys, and fallback chain; swap only the HTTP layer inside `ElevenLabsTtsProvider` (or a thin adapter).
3. **TLS:** thread the same CA / verify settings into whatever HTTP stack the SDK uses (or keep httpx if the SDK cannot be configured).
4. **Tests:** mock at provider boundary; no live API in CI.
5. **Docs:** `.env.example` + CONTRIBUTING note if new env vars appear.

## Non-goals (for this plan)

- Replacing `/speak` with **ElevenAgents** `Conversation` / live mic sessions.
- Expecting the SDK to fix **SSL** without CA bundle or verify toggle.

## Next step after merge

- Decide “stay on httpx” vs “spike official client” based on maintenance and TLS configurability.
