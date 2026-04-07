from __future__ import annotations

import functools
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent


class CruxSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    CRUX_ENABLED: bool = True

    CRUX_TTS_ENABLED: bool = True
    CRUX_AMBIENT_ENABLED: bool = False
    CRUX_REVIEWER_ENABLED: bool = True
    CRUX_COMMITTER_ENABLED: bool = True
    CRUX_WATCHER_ENABLED: bool = True
    CRUX_NARRATOR_ENABLED: bool = True
    CRUX_SEMANTIC_CACHE_ENABLED: bool = True
    CRUX_EXACT_CACHE_ENABLED: bool = True

    CRUX_HOST: str = "127.0.0.1"
    CRUX_PORT: int = 9090
    CRUX_LOG_LEVEL: str = "info"
    CRUX_INTERNAL_SECRET: str = ""

    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "qwen/qwen3-coder:free"
    OPENROUTER_FALLBACK_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
    OPENROUTER_EMBEDDING_MODEL: str = "openai/text-embedding-3-small"
    CLAUDE_ENABLED: bool = False
    ANTHROPIC_API_KEY: str = ""
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    CRUX_LLM_PROVIDER: str = "openrouter"

    CRUX_TTS_VOICE: str = "en-US-JennyNeural"
    CRUX_TTS_RATE: str = "+7%"
    CRUX_TTS_PITCH: str = "+2Hz"
    CRUX_TTS_VOICE_BLOCK: str = ""
    CRUX_TTS_LOCK_TTL_SEC: int = 600
    CRUX_TTS_STREAM: bool = True
    CRUX_TTS_FALLBACK: str = "none"
    # Optional JSON overlay merged over bundled `server/tts/data/tts_registry.json`
    CRUX_TTS_CONFIG_PATH: str = ""
    # auto: use locale chain; say | edge: force provider when allowed for locale
    CRUX_TTS_PROVIDER: str = ""
    # False removes `edge` from platform-allowed providers (say-only on Mac when possible)
    CRUX_EDGE_TTS_ENABLED: bool = True
    CRUX_SAY_RATE_WPM: int = 200
    # Optional absolute path to `say` (default: PATH)
    CRUX_SAY_PATH: str = ""
    CRUX_SAY_VOICE_DEFAULT: str = "Samantha"
    CRUX_SAY_VOICE_BLOCK: str = ""
    # Absolute path to ffplay if not on PATH (e.g. /opt/homebrew/bin/ffplay)
    CRUX_FFPLAY_PATH: str = ""
    # Windows: optional SDL_AUDIODRIVER. Empty = inherit process env (OpenClaw default).
    CRUX_SDL_AUDIODRIVER: str = ""
    # Windows only: hide ffplay console (CREATE_NO_WINDOW). Set false to debug visibly.
    CRUX_FFPLAY_WINDOWS_NO_WINDOW: bool = True

    # ElevenLabs (chain: eleven first, then say on macOS, then edge). API key from app settings.
    CRUX_ELEVENLABS_ENABLED: bool = True
    CRUX_ELEVENLABS_API_KEY: str = ""
    CRUX_ELEVENLABS_BASE_URL: str = "https://api.elevenlabs.io"
    # basic | medium | best → see server/tts/eleven_models.py
    CRUX_ELEVENLABS_MODEL_TIER: str = "basic"
    CRUX_ELEVENLABS_VOICE_ID: str = ""
    CRUX_ELEVENLABS_OUTPUT_FORMAT: str = "mp3_44100_128"
    CRUX_ELEVENLABS_VOICE_BLOCK: str = ""
    CRUX_ELEVENLABS_TIMEOUT_SEC: float = 120.0
    # PEM bundle path for TLS to ElevenLabs (corporate proxy CA). Empty = httpx default CAs.
    CRUX_ELEVENLABS_SSL_CA_BUNDLE: str = ""
    # Set false only to debug MITM or broken trust stores; insecure on public networks.
    CRUX_ELEVENLABS_VERIFY_TLS: bool = True
    # Redis cache for synthesized MP3 (cleared on server startup); 3600 = 1 hour
    CRUX_TTS_ELEVEN_CACHE_TTL_SEC: int = 3600

    REDIS_URL: str = "redis://127.0.0.1:6379"
    DATABASE_URL: str = "postgresql://crux:crux@127.0.0.1:5433/crux"
    EMBEDDING_DIM: int = 1536

    CACHE_TTL_SEC: int = 3600
    CACHE_SEMANTIC_THRESHOLD: float = 0.95
    CACHE_SEMANTIC_MAX_AGE_DAYS: int = 7
    CACHE_EMBED_TTL_SEC: int = 300

    CRUX_GIT_AUTO_COMMIT: bool = True
    CRUX_GIT_COMMIT_INTERVAL_MIN: int = 60
    CRUX_GIT_AUTO_MR: bool = True
    CRUX_GIT_TARGET_BRANCH: str = ""
    CRUX_GIT_REPO_PATH: str = "."

    CRUX_HOURLY_CONFIRM_TIMEOUT_SEC: int = 600
    CRUX_HOURLY_REBASE_ON_TIMEOUT: bool = False

    CRUX_LISTEN_ENABLED: bool = False
    CRUX_WHISPER_MODEL: str = "small"

    CRUX_AMBIENT_INTERVAL_SEC: int = 1800

    CRUX_USER_NAME: str = "Developer"
    CRUX_USER_TZ: str = "UTC"

    CRUX_FORGE_VOICE: str = ""
    CRUX_FORGE_RATE: str = ""
    CRUX_SENTINEL_VOICE: str = ""
    CRUX_SENTINEL_RATE: str = ""
    CRUX_CHRONICLE_VOICE: str = ""
    CRUX_CHRONICLE_RATE: str = ""
    CRUX_SAGE_VOICE: str = ""
    CRUX_SAGE_RATE: str = ""
    CRUX_MAESTRO_VOICE: str = ""
    CRUX_MAESTRO_RATE: str = ""
    CRUX_ECHO_VOICE: str = ""
    CRUX_ECHO_RATE: str = ""

    CRUX_FORGE_SAY_VOICE: str = ""
    CRUX_SENTINEL_SAY_VOICE: str = ""
    CRUX_CHRONICLE_SAY_VOICE: str = ""
    CRUX_SAGE_SAY_VOICE: str = ""
    CRUX_MAESTRO_SAY_VOICE: str = ""
    CRUX_ECHO_SAY_VOICE: str = ""

    CRUX_REVIEWER_INTERVAL_MIN: int = 15
    CRUX_WATCHER_DEBOUNCE_SEC: float = 5.0
    # When true, file watcher triggers Echo TTS (races with /speak on generation counter).
    CRUX_WATCHER_SPEAK_ENABLED: bool = False


@functools.lru_cache
def get_settings() -> CruxSettings:
    return CruxSettings()
