# Crux

Crux is a **standalone**, macOS-oriented voice-enabled AI coding assistant: a FastAPI server on `127.0.0.1` (default port **9090**), **speech** via pluggable providers (`say`, **Edge TTS** / `edge-tts` + **ffplay**) selected by **`TtsService`** from **`server/tts/data/tts_registry.json`** (locales, chains, persona overrides). Extend with **`CRUX_TTS_CONFIG_PATH`**. **Redis** speaker locking, **PostgreSQL + pgvector** for semantic cache, and **Cursor** rules/skills. No OpenClaw runtime imports.

**Monorepo layout (OpenClaw):** In the full OpenClaw tree, this project lives at `openclaw/crux/` with the normative spec at `openclaw/docs/crux-standalone-project-spec.md`. This repository can also be used as a **standalone** checkout with the same `crux/` layout at the root.

## Prerequisites (macOS)

- Homebrew
- Python **3.12+**
- **Docker** (Desktop or Colima) for Postgres + Redis
- **ffmpeg** (for `ffplay`) when using Edge TTS; optional if you only use macOS `say`
- **git**, **gh**, **curl**, **jq**

## Quick start

```bash
make setup          # or: bash scripts/setup.sh
# Edit .env — set OPENROUTER_API_KEY and CRUX_INTERNAL_SECRET
make docker-up
make run            # server on CRUX_HOST:CRUX_PORT (default 127.0.0.1:9090)
# For a second instance, set CRUX_PORT in `.env` or `CRUX_PORT=9191 make run`.
```

In another terminal:

```bash
export CRUX_BASE_URL=http://127.0.0.1:9090   # optional if default
make speak TEXT="hello world"                # scripts/speak.sh → /speak-async
# or: bash scripts/speak.sh "hello" 1        # priority preempt
# Windows: powershell -NoProfile -ExecutionPolicy Bypass -File scripts/speak.ps1 "hello" 1
```

**Contributing & agents:** **`CONTRIBUTING.md`** — setup, API/`curl` examples, personas, code style. Cursor rules stay short and point there.

Open the **`crux/`** folder in Cursor so workspace rules apply.

## API (v1)

| Method | Path | Notes |
|--------|------|--------|
| GET | `/health` | Redis, Postgres, daemon health flags |
| POST | `/speak` | JSON: `text`, optional `persona`, `priority` |
| POST | `/speak-async` | **202** — fire-and-forget |
| POST | `/llm/chat` | `prompt`, `system`, optional `source` |
| POST | `/git/commit` | optional `message` |
| POST | `/git/review` | JSON `diff` |
| POST | `/git/mr` | `title`, `body`, optional `base` |
| GET | `/git/status` | branch, change count, last commit |
| POST | `/internal/hourly-decision` | Header `X-Crux-Secret`, body `{"decision":"yes"\|"no"}` |

## Troubleshooting

- **Edge TTS fails on macOS (SSL/network):** set `CRUX_EDGE_TTS_ENABLED=false` or put **`say`** first in the locale `chain` inside `tts_registry.json` (or your `CRUX_TTS_CONFIG_PATH` overlay). Tune `say` via `CRUX_SAY_RATE_WPM` / `CRUX_*_SAY_VOICE` and per-locale `voices.say` in JSON. List macOS voices: `say -v '?'`.
- **No audio (Edge path):** ensure `ffplay` is on `PATH` (`brew install ffmpeg`) or set `CRUX_FFPLAY_PATH`.
- **Redis down:** speaker lock falls back to a temp-file guard; `bash scripts/clear-locks.sh` clears state.
- **Edge TTS errors / 429:** retry later; optional `CRUX_TTS_FALLBACK=notify` for a macOS notification only (no `say` persona speech).
- **Hourly rebase conflicts:** see `var/hourly-rebase-failure.log`; resolve manually — Crux does not force-push.

## License

MIT — see [LICENSE](LICENSE).
