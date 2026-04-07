# Contributing to Crux

Stack, ports, scripts, and personas live **here** — not in Cursor rules (rules stay portable and call **HTTP only**).

## Setup and run

1. `make setup` (venv + deps).
2. `make docker-up` for Redis/Postgres when you need them.
3. Start the API (pick one):
   - Foreground: `make run`
   - Background: `make start-server` or `bash scripts/crux-service.sh start-server`
   - **macOS TTS reliability:** `make start-server-terminal` (Terminal.app session).
4. **Agent integration:** export **`CRUX_BASE_URL`** (default `http://127.0.0.1:9090`) in your shell. The server reads **`.env`**; agents should not parse `.env` in rules.

Optional helper: `python scripts/crux_client.py -h` — for git/LLM/health; **`speak`** subcommand runs **`scripts/speak.sh`** (same as agents).

**Speech client:** **`bash scripts/speak.sh "text" [0|1] [persona]`** or **`--sync`** for blocking `/speak`. This is the only supported way to trigger voice (server queues non-priority requests; **`priority 1`** preempts).

### Browser voice UI (ElevenLabs agent + Crux bridge)

1. Set **`CRUX_ELEVENLABS_AGENT_ID`**, **`CRUX_ELEVENLABS_API_KEY`**, and **`CRUX_VOICE_OUTPUT=browser`** (or **`auto`**) in **`.env`**.
2. Start Crux (`make run` or equivalent on port **9090**).
3. In another shell: **`cd web/voice-agent && npm install && npm run dev`** (Vite proxies **`/voice`** to Crux). Open **`http://127.0.0.1:5173`**.
4. Click **Start voice** (ConvAI session). Cursor narration via **`speak.sh`** appears as **narrator** lines when at least one browser tab has an open **`/voice/ws`** connection.
5. **Stop → Crux** ends the agent session and **`POST /voice/downflow`** with the user transcript + recent thread to **`/llm/chat`**.

Copy **`web/voice-agent/.env.example`** → **`.env`**: **`VITE_CRUX_BASE`**, **`VITE_CRUX_WS_ORIGIN`** (optional; defaults to **`ws://127.0.0.1:9090`** when base empty), **`VITE_CRUX_VOICE_SECRET`** (must match **`CRUX_VOICE_WS_SECRET`** if set). **`web/voice-agent/.env`** is gitignored.

## Tests and style

```bash
make test
# or: ruff check . && ruff format --check . && pytest tests/ -q
```

**Hear every persona (verbose samples):** with Crux running, `make test-tts-voices` (sync `/speak`, long) or `make test-tts-voices-async` (queued `/speak-async`). See `scripts/test_tts_voices.sh`.

- **Python:** 3.12+; `from __future__ import annotations` where helpful; async for I/O; **structlog** (not `print`) in server code; import order stdlib → third-party → local (ruff).
- **FastAPI:** `APIRouter`; dependencies for config/Redis/Postgres; **lifespan** for startup/shutdown; Pydantic v2 request/response models.
- **Tests:** `pytest` + `pytest-asyncio`; mirror module layout under `tests/`; mock LLM and network; `monkeypatch` for env.

Git integration tests need a normal `git init` (some sandboxes skip if hooks fail).

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description` — types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `style`, `perf`, `ci`.

## Branches and merge requests

- **Do not push straight to `main`** when it may be protected. Commit on a **feature branch**, **push** it, then open an **MR** (GitLab) or **PR** (GitHub).
- **Branch format:** `{type}/{JIRA-KEY}-{short-kebab-description}` — e.g. `feat/CRUX-12-elevenlabs-tls`. Types align with commits (`feat`, `fix` for bugs, `chore`, `docs`, …). **Agents:** if the user did not provide a **JIRA issue key**, ask before naming the branch.
- Open MRs via **`POST /git/mr`** when the server is up (**`/health`**), or **`gh pr create`** / the host’s MR creation URL. Cursor rule: **`.cursor/rules/023-mr-creation.mdc`**.

## HTTP API (for agents)

All paths are under **`CRUX_BASE_URL`**. Examples use `$B` = `"${CRUX_BASE_URL:-http://127.0.0.1:9090}"`.

| Endpoint | Notes |
|----------|--------|
| `GET /health` | Liveness |
| `POST /speak-async` | `{"text","priority"?, "persona"?}` — non-blocking |
| `POST /speak` | Same body; waits for playback |

**Agent narration:** Use **`scripts/speak.sh`** (skill **`speak`**), not raw `curl` to `/speak`. Rule **`000-agent-http.mdc`** defines timing and **`priority`**. Non-priority speech **queues** on the server (generation counter is not bumped per request, so clips do not cancel each other).
| `GET /git/status` | Branch, dirty count, last commit |
| `POST /git/commit` | `{"message"}` — server runs `git add -A` + commit in its repo |
| `POST /git/review` | `{"diff":"..."}` |
| `POST /git/mr` | `{"title","body","base"?}` — runs `gh pr create` on server |
| `POST /llm/chat` | `{"prompt","system"?,"source"?}` |
| `GET /voice/convai/signed-url` | Query **`agent_id`** optional; returns **`signed_url`** for **`@elevenlabs/client`** (server uses API key) |
| `WebSocket /voice/ws` | Narration fan-out; optional query **`secret`** = **`CRUX_VOICE_WS_SECRET`** |
| `POST /voice/downflow` | `{"transcript","messages"?,"system"?,"source"?}` → LLM; optional header **`X-Crux-Voice-Secret`** |
| `POST /internal/hourly-decision` | `{"decision":"yes\|no"}` + header **`X-Crux-Secret`** (must match server; export in shell, never commit) |

**Review with diff from repo:**

```bash
B="${CRUX_BASE_URL:-http://127.0.0.1:9090}"
git diff | jq -Rs '{diff: .}' | curl -sS -X POST "$B/git/review" -H 'Content-Type: application/json' -d @-
```

## Personas (TTS / `persona` field)

| key | role | typical use |
|-----|------|-------------|
| forge | Chief Architect | default, ack, progress, done |
| sentinel | Code Guardian | review, pre-commit |
| chronicle | Release Engineer | commit, MR, hourly |
| sage | Research Analyst | analysis |
| maestro | Operations | ambient-style |
| echo | Context Keeper | file/context updates |
| priya | (example) Hindi `hi-IN` / Edge-oriented chain | `persona=priya` in `/speak` |
| siri | System assistant | Siri-style **`say`** / Edge assistant voice — see voice table below |

Voices, locale chains, and overrides: **`server/tts/data/tts_registry.json`**. Overlay: **`CRUX_TTS_CONFIG_PATH`**. Legacy `.env` voice keys still merge at load — see `.env.example`.

**Voice pool (v2 registry):** Top-level **`voice_pool`** lists the only **Edge** and **`say`** voice IDs allowed for defaults and personas (curated from Microsoft **Multilingual / conversation Neural** voices and common macOS **Enhanced** names). Extend the pool before adding new persona voices; **`tests/test_tts_registry.py`** asserts every locale/persona voice is in the pool.

| Persona | Role | Typical `say` (pool) | Typical Edge (pool) |
|---------|------|----------------------|---------------------|
| forge | Architect | Samantha | en-US-AvaMultilingualNeural |
| sentinel | Guardian | Fred | en-US-AndrewMultilingualNeural |
| chronicle | Release | Daniel | en-GB-SoniaNeural |
| sage | Analyst | Samantha (slower) | en-US-EmmaMultilingualNeural |
| maestro | Ops | Kathy | en-US-JennyNeural |
| echo | Context | Moira | en-IE-ConnorNeural |
| priya | Hindi | — | hi-IN-MadhurNeural |
| siri | Siri-style | Aman | en-US-AvaMultilingualNeural |

Adding a persona: row in `server/personas/registry.py` (`key`, `name`, `title`, `actions`) + matching `personas` entry in `tts_registry.json` **using only `voice_pool` voices**, then extend **`voice_pool`** if you need a new ID.

## Adding a daemon

1. Subclass `server/daemons/base.py` `BaseDaemon`, implement `run_loop`.
2. Flag in `server/config.py` + `.env.example`.
3. Register in `server/main.py` lifespan.

## STT / listen

`CRUX_LISTEN_ENABLED` stays off in v1; future backends can post to `/internal/hourly-decision`. Keep secrets out of logs.

## Security

Never commit real `.env` or API keys.
