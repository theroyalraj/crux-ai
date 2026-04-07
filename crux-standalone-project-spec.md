# Crux — Standalone voice-enabled AI coding assistant (full implementation spec)

**Audience:** Any coding agent or human implementing the project.  
**Host monorepo:** OpenClaw (`d:\code\openclaw` or equivalent).  
**Code root (to be created):** `crux/` at the repository root, **standalone** (no runtime imports from `pc-agent/`, `skill-gateway/`, or other OpenClaw packages).  
**Spec artifact:** This file — `docs/crux-standalone-project-spec.md`.

**Platform v1:** macOS only (extensible architecture later).  
**Branding:** **Crux** everywhere — not OpenClaw, not Forgemaster.  
**Voice:** Primary path is **Microsoft Edge TTS** via Python **`edge-tts`**, playback only via **`ffplay`** (from Homebrew **`ffmpeg`**). **Default Edge voice** for global TTS settings and **Forge** (chief architect) persona is **`en-US-JennyNeural`** — friendly, bright assistant timbre; override with `CRUX_TTS_VOICE` / `CRUX_FORGE_VOICE` in `.env` if you prefer another allowed id.  
**LLM:** **OpenRouter** free-tier models primary; **Claude** optional secondary.  
**No web UI v1:** FastAPI server + shell scripts + Cursor `.cursor/` rules and skills only.

---

## Table of contents

1. [Goals and non-goals](#1-goals-and-non-goals)
2. [Global naming conventions](#2-global-naming-conventions)
3. [Repository layout inside OpenClaw](#3-repository-layout-inside-openclaw)
4. [Complete directory structure](#4-complete-directory-structure)
5. [Part A — Cursor rules (all `.mdc` files)](#5-part-a--cursor-rules-all-mdc-files)
6. [Part B — Cursor skills (all `SKILL.md` files)](#6-part-b--cursor-skills-all-skillmd-files)
7. [Part C — Python server](#7-part-c--python-server)
8. [Part D — Hourly commit daemon (normative state machine)](#8-part-d--hourly-commit-daemon-normative-state-machine)
9. [Part E — TTS and audio](#9-part-e--tts-and-audio)
10. [Part F — Redis speaker lock](#10-part-f--redis-speaker-lock)
11. [Part G — Docker and SQL](#11-part-g--docker-and-sql)
12. [Part H — Scripts and Makefile](#12-part-h--scripts-and-makefile)
13. [Part I — Environment template](#13-part-i--environment-template)
14. [Part J — Dependencies](#14-part-j--dependencies)
15. [Part K — README and CONTRIBUTING expectations](#15-part-k--readme-and-contributing-expectations)
16. [Part L — Implementation order](#16-part-l--implementation-order)
17. [Part M — Verification checklist](#17-part-m--verification-checklist)
18. [Part N — Security and safety](#18-part-n--security-and-safety)
19. [Appendix — OpenClaw reference code (read-only)](#appendix--openclaw-reference-code-read-only)

---

## 1. Goals and non-goals

### Goals

- **Cursor integration** via rich `.cursor/rules` and `.cursor/skills`.
- **Single FastAPI process** on **`127.0.0.1:9090`** (default) with async lifespan, multiple asyncio daemons.
- **Edge TTS** synthesis + **`ffplay`** playback; **Redis** distributed lock so only one utterance plays at a time (with priority preempt).
- **Personas** mapped by **ACTION** (ack, review, commit, …), not by chat session.
- **OpenRouter** as primary LLM; **semantic + exact** caching (Postgres **pgvector** + Redis).
- **Automated git workflows:** review endpoints, smart commit message, MR via **`gh`**, **hourly checkpoint** with **spoken** prompt, **10-minute** confirmation window, **default no** on timeout, **`git fetch` + `git rebase origin/<defaultBranch>`** after **explicit yes or no**, with **user-visible failure** on rebase conflict.
- **Feature flags** in `.env`: master kill switch + per-feature toggles.
- **One-command macOS bootstrap** via `scripts/setup.sh` including Docker services and **`ffplay`** availability.

### Non-goals (v1)

- Windows or Linux support in setup scripts.
- Browser or native GUI.
- Tight coupling to OpenClaw runtime services.

---

## 2. Global naming conventions

| Concept | Value |
|--------|--------|
| Product / Python distribution name | `crux` |
| Master env flag | `CRUX_ENABLED` |
| Feature flags | `CRUX_TTS_ENABLED`, `CRUX_COMMITTER_ENABLED`, … |
| HTTP | `CRUX_HOST` (default `127.0.0.1`), `CRUX_PORT` (default `9090`) |
| Redis key prefix | `crux:` |
| Docker volume names | `crux_postgres`, `crux_redis` |
| DB user / database (default in compose) | `crux` |
| Internal API secret header | `X-Crux-Secret` → env `CRUX_INTERNAL_SECRET` |
| Temp audio / pkill pattern token | include substring **`crux-tts`** in ffplay args or temp path so `pkill -f 'ffplay.*crux-tts'` does not kill unrelated user ffplay |

Replace every historical **Forgemaster** / `FORGE_*` / `forge:` name from older drafts with the table above.

---

## 3. Repository layout inside OpenClaw

```
openclaw/
├── docs/
│   └── crux-standalone-project-spec.md   ← this file
├── crux/                                 ← standalone project (create when implementing)
│   ├── .cursor/
│   ├── server/
│   ├── docker/
│   ├── scripts/
│   ├── tests/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── Makefile
│   └── ...
├── pc-agent/
├── skill-gateway/
└── ...
```

Implementers work primarily under **`crux/`**; this document lives under **`docs/`** for discoverability in the monorepo.

---

## 4. Complete directory structure

```
crux/
├── .cursor/
│   ├── rules/
│   │   ├── 000-agent-http.mdc
│   │   ├── 001-project-standards.mdc
│   │   ├── 002-persona-registry.mdc
│   │   ├── 020-commit-conventions.mdc
│   │   ├── 021-pre-commit-review.mdc
│   │   ├── 022-hourly-checkpoint.mdc
│   │   ├── 023-mr-creation.mdc
│   │   ├── 030-wip-safety-commit.mdc
│   │   └── 050-no-markdown-in-speech.mdc
│   └── skills/
│       ├── speak/SKILL.md
│       ├── commit/SKILL.md
│       ├── review/SKILL.md
│       ├── mr/SKILL.md
│       └── hourly-report/SKILL.md
│
├── server/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── openrouter_client.py
│   │   ├── claude_client.py
│   │   └── cache.py
│   ├── tts/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   ├── speaker.py
│   │   ├── voices.py
│   │   └── lock.py
│   ├── personas/
│   │   ├── __init__.py
│   │   ├── registry.py
│   │   └── resolver.py
│   ├── daemons/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── narrator.py
│   │   ├── reviewer.py
│   │   ├── committer.py
│   │   ├── ambient.py
│   │   └── watcher.py
│   ├── git/
│   │   ├── __init__.py
│   │   ├── ops.py
│   │   ├── review.py
│   │   └── mr.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── postgres.py
│   │   └── redis_client.py
│   └── routes/
│       ├── __init__.py
│       ├── health.py
│       ├── speak.py
│       ├── llm.py
│       ├── git_routes.py
│       └── internal.py
│
├── docker/
│   ├── docker-compose.yml
│   └── postgres/
│       └── init/
│           ├── 01-extensions.sql
│           └── 02-ai-cache.sql
│
├── scripts/
│   ├── setup.sh
│   ├── speak.sh
│   └── clear-locks.sh
│
├── tests/
│   ├── __init__.py
│   ├── test_lock.py
│   ├── test_cache.py
│   ├── test_personas.py
│   ├── test_git_ops.py
│   └── test_hourly_committer.py
│
├── var/
│   └── .gitkeep                  # optional: logs for hourly failures, etc.
│
├── .env.example
├── requirements.txt
├── pyproject.toml
├── Makefile
├── README.md
├── CONTRIBUTING.md
└── LICENSE                       # MIT
```

**Note:** Add `server/routes/internal.py` for secured internal endpoints (hourly decision). The original Forgemaster sketch omitted it.

---

## 5. Part A — Cursor rules (all `.mdc` files)

Each file lives in `crux/.cursor/rules/`. Use Cursor MDC frontmatter as shown.

### 5.1 `001-project-standards.mdc`

```yaml
---
description: Crux core tech stack, commands, and boundaries
alwaysApply: true
---
```

**Body (summary for implementers — paste as rule text):**

- **Stack:** Python 3.12+, FastAPI, asyncio, `edge-tts`, Redis, PostgreSQL + pgvector, `gh` CLI, Docker Compose.
- **Style:** `ruff` format + lint; type hints on all public functions; async-first for I/O.
- **Commands:** `make setup`, `make run`, `make test`, `make speak TEXT="hello"`, `make docker-up`, `make docker-down`, `make clean`.
- **TTS from Cursor:** `bash scripts/speak.sh "plain English" [1]` — second arg `1` means priority (preempt).
- **Config:** All behavior toggles live in **`crux/.env`** (copy from `.env.example`). Never commit real `.env`.
- **Forbidden:** Do not kill or restart the Crux server process unless the user explicitly asks. Do not `docker compose down` without user request. Do not commit secrets.

### 5.2 `002-persona-registry.mdc`

```yaml
---
description: Crux persona roster — voices and action mapping
alwaysApply: true
---
```

**Personas (action-based):**

| Key | Name | Title | Default Edge voice | Rate hint | Actions |
|-----|------|-------|-------------------|-----------|---------|
| forge | Forge | Chief Architect | `en-US-JennyNeural` | default | acknowledge, narrate, completion, general |
| sentinel | Sentinel | Code Guardian | `en-US-GuyNeural` | +5% | review, security_scan, pre_commit |
| chronicle | Chronicle | Release Engineer | `en-GB-SoniaNeural` | default | commit, mr, hourly_checkpoint, changelog |
| sage | Sage | Research Analyst | `en-US-EmmaMultilingualNeural` | -5% | thinking, analysis, explanation |
| maestro | Maestro | Operations Lead | `en-US-MichelleNeural` | -2% | ambient, break_reminder, hydration, posture |
| echo | Echo | Context Keeper | `en-IE-ConnorNeural` | +3% | file_watch, transcript, context_update |

**Rule text:**

- Refer to personas by name in explanations where helpful.
- Each **daemon** speaks with **one** persona per action; do not mix voices within a single spoken action.
- Persona is chosen by **ACTION**, not Cursor chat session.
- Voices may be overridden in `.env`: `CRUX_FORGE_VOICE`, `CRUX_SENTINEL_VOICE`, … and `CRUX_FORGE_RATE`, etc. (match resolver implementation in `server/personas/resolver.py`).

### 5.3 `010-acknowledge-before-work.mdc`

```yaml
---
description: USE WHEN starting any task — async TTS acknowledgement alongside first tool use
alwaysApply: false
---
```

- Before planning, fire: `bash scripts/speak.sh "Got it, diving in." 1` (vary wording; under ~12 words; conversational).
- Must be **non-blocking** for the agent; `speak.sh` returns immediately.
- Priority `1` cuts ahead of queued speech.

### 5.4 `011-narrate-progress.mdc`

```yaml
---
description: USE WHEN a task runs longer than ~30 seconds with meaningful milestones
alwaysApply: false
---
```

- Short spoken updates at milestones; use **normal** priority unless urgent.
- **Cooldown:** at most one mid-task narration per **2 minutes** (rule for agents — server may optionally enforce rate limits).
- No file paths, hashes, or code snippets in speech; plain English only.
- See `050-no-markdown-in-speech.mdc`.

### 5.5 `012-completion-summary.mdc`

```yaml
---
description: USE WHEN finishing a substantive task (code change, review, commit flow)
alwaysApply: false
---
```

- Always speak a **2–3 sentence** summary with priority: `bash scripts/speak.sh "Done — …" 1`
- Cover: what changed, risks, follow-ups.

### 5.6 `020-commit-conventions.mdc`

```yaml
---
description: USE WHEN writing commit messages or staging commits
alwaysApply: false
---
```

- **Conventional Commits:** `type(scope): description`
- Types: feat, fix, refactor, test, docs, chore, style, perf, ci
- Imperative mood; ~72 chars subject; body explains **why**.
- Footer: `Co-Authored-By: Cursor AI <noreply@cursor.com>` when appropriate.
- Before commit: run checks per `021-pre-commit-review.mdc`.

### 5.7 `021-pre-commit-review.mdc`

```yaml
---
description: USE WHEN about to git commit — quality gates
alwaysApply: false
---
```

- `ruff check .`
- `ruff format --check .`
- `python -m pytest tests/ -x -q`
- Manual scan: secrets, large commented-out blocks, stale TODO without ticket
- Exceptions: typo-only, docs-only, `.env.example` only.
- May speak via Sentinel persona for notable findings.

### 5.8 `022-hourly-checkpoint.mdc`

```yaml
---
description: USE WHEN asked for hourly review or aligning with CommitterDaemon behavior
alwaysApply: false
---
```

**Normative behavior (must match server):**

1. `git log --since="1 hour ago"` and `git diff --stat` / `git diff`.
2. If **dirty** working tree: summarize (LLM or template), **speak** via Chronicle, then **wait up to 10 minutes** for **yes/no** (voice STT and/or `POST /internal/hourly-decision`).
3. **Timeout** ⇒ treat as **no** for auto-commit / push / PR.
4. On **explicit yes or no**: `git fetch` and **`git rebase origin/<defaultBranch>`** (default branch from `gh` or `origin/HEAD`). On **rebase conflict**: **stop**, **inform user** (spoken + logs). No auto force-push.
5. If **yes** and rebase **ok**: commit (if configured), push, optional `gh pr create`.
6. If **no**: skip commit/MR; rebase still applied if user explicitly answered (not on timeout unless `CRUX_HOURLY_REBASE_ON_TIMEOUT=true`).

### 5.9 `023-mr-creation.mdc`

```yaml
---
description: USE WHEN creating a merge or pull request
alwaysApply: false
---
```

- Branches: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`
- Use `gh pr create`; base branch from repo default or `CRUX_GIT_TARGET_BRANCH`.
- MR body: Summary, Changes, Test Plan; footer `Generated by Crux`.

### 5.10 `030-wip-safety-commit.mdc`

```yaml
---
description: USE BEFORE risky refactors — checkpoint branch
alwaysApply: false
---
```

- Branch `wip/checkpoint-<slug>-<YYYYMMDD>`
- Commit `wip: stable checkpoint before …`
- Speak short confirmation via Forge persona.

### 5.11 `000-agent-http.mdc` (always apply)

- Agents use **HTTP only** (`curl` + `CRUX_BASE_URL`) for speak, git, LLM; server does synthesis and side effects.
- No local `say` as default; no reading `.env` in rules. See **`CONTRIBUTING.md`** for endpoint table and examples.

### 5.12 Python / FastAPI / tests

- **Normative detail:** **`CONTRIBUTING.md`** (replaces former `040`–`042` rule files).

### 5.13 `050-no-markdown-in-speech.mdc`

```yaml
---
description: Spoken text must be plain English — no markdown or symbols
alwaysApply: true
---
```

- Ban `*`, `` ` ``, `#`, bullets, URLs, percents, arrows, backticks, etc., in **`POST /speak` / `/speak-async`** `text`.
- Say "three files" not "3 files"; "percent" not "%".
- Server SHOULD normalize text before Edge TTS as defense in depth.

---

## 6. Part B — Cursor skills (all `SKILL.md` files)

Paths: `crux/.cursor/skills/<name>/SKILL.md`. **Speech:** **`speak/SKILL.md`** + **`scripts/speak.sh`** only. Other APIs: **`CRUX_BASE_URL`** + **`curl`** per **`CONTRIBUTING.md`** and **`000-agent-http.mdc`**.

### 6.1–6.4

- **commit / review / mr / hourly-report:** health check → **`POST`** to `/git/commit`, `/git/review`, `/git/mr`, `/llm/chat`, `/speak-async`, `/internal/hourly-decision` as appropriate; fallback to plain `git`/`gh` if server unreachable. Full steps live in each **`SKILL.md`** (kept brief).

---

## 7. Part C — Python server

### 7.1 `server/config.py` — `CruxSettings`

Subclass `pydantic_settings.BaseSettings` with `env_file=".env"`, `extra="ignore"`.

**Fields (implement all):**

```python
# Master
CRUX_ENABLED: bool = True

# Features
CRUX_TTS_ENABLED: bool = True
CRUX_AMBIENT_ENABLED: bool = False
CRUX_REVIEWER_ENABLED: bool = True
CRUX_COMMITTER_ENABLED: bool = True
CRUX_WATCHER_ENABLED: bool = True
CRUX_NARRATOR_ENABLED: bool = True
CRUX_SEMANTIC_CACHE_ENABLED: bool = True
CRUX_EXACT_CACHE_ENABLED: bool = True

# Server
CRUX_HOST: str = "127.0.0.1"
CRUX_PORT: int = 9090
CRUX_LOG_LEVEL: str = "info"
CRUX_INTERNAL_SECRET: str = ""  # required if internal routes enabled

# LLM
OPENROUTER_API_KEY: str = ""
OPENROUTER_MODEL: str = "qwen/qwen3-coder:free"
OPENROUTER_FALLBACK_MODEL: str = "meta-llama/llama-3.3-70b-instruct:free"
CLAUDE_ENABLED: bool = False
ANTHROPIC_API_KEY: str = ""
CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
CRUX_LLM_PROVIDER: str = "openrouter"  # openrouter | claude | auto

# TTS
CRUX_TTS_VOICE: str = "en-US-JennyNeural"
CRUX_TTS_RATE: str = "+7%"
CRUX_TTS_PITCH: str = "+2Hz"
CRUX_TTS_VOICE_BLOCK: str = ""  # comma-separated ids
CRUX_TTS_LOCK_TTL_SEC: int = 600
CRUX_TTS_STREAM: bool = True
CRUX_TTS_FALLBACK: str = "none"  # none | notify (see Part E)

# Redis / Postgres
REDIS_URL: str = "redis://127.0.0.1:6379"
DATABASE_URL: str = "postgresql://crux:crux@127.0.0.1:5433/crux"
EMBEDDING_DIM: int = 1536

# Cache
CACHE_TTL_SEC: int = 3600
CACHE_SEMANTIC_THRESHOLD: float = 0.95
CACHE_SEMANTIC_MAX_AGE_DAYS: int = 7
CACHE_EMBED_TTL_SEC: int = 300

# Git
CRUX_GIT_AUTO_COMMIT: bool = True
CRUX_GIT_COMMIT_INTERVAL_MIN: int = 60
CRUX_GIT_AUTO_MR: bool = True
CRUX_GIT_TARGET_BRANCH: str = ""  # empty = auto-detect default branch
CRUX_GIT_REPO_PATH: str = "."

# Hourly confirmation
CRUX_HOURLY_CONFIRM_TIMEOUT_SEC: int = 600
CRUX_HOURLY_REBASE_ON_TIMEOUT: bool = False

# Listen / STT (optional)
CRUX_LISTEN_ENABLED: bool = False
CRUX_WHISPER_MODEL: str = "small"  # for faster-whisper or equivalent

# Ambient
CRUX_AMBIENT_INTERVAL_SEC: int = 1800

# User
CRUX_USER_NAME: str = "Developer"
CRUX_USER_TZ: str = "UTC"
```

Singleton accessor `get_settings() -> CruxSettings` cached on first call.

### 7.2 Application entry `server/main.py`

- `FastAPI(title="Crux", lifespan=lifespan)`
- Routers: `health`, `speak`, `llm`, `git_routes`, `internal` (internal mounted with dependency that validates `X-Crux-Secret`).
- **lifespan:**
  - If not `CRUX_ENABLED`: log and yield minimal app (health still ok) or exit — **spec recommends** still run health but skip daemons.
  - Else: `init_redis`, `init_postgres`, construct daemons list, `start()` each, `yield`, then **reverse stop**, **`kill_all_audio()`**, **`force_clear_all_locks()`**, `cleanup_temp_files`, close pools.

### 7.3 Routes (summary)

| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| GET | `/health` | none | | `status`, `daemons`, `redis`, `postgres` booleans |
| POST | `/speak` | optional Bearer or none per your threat model | `text`, `persona` key optional, `priority` | `ok`, `duration_sec` approx |
| POST | `/speak-async` | same | same | `202` accepted |
| POST | `/llm/chat` | | `prompt`, `system`, `source` | `response`, `cached`, `cache_hit_type` optional |
| POST | `/git/commit` | | `message` auto or string | hash, message |
| POST | `/git/review` | | `diff` | issues, score, summary |
| POST | `/git/mr` | | `title`, `body`, `base` optional | `url` |
| GET | `/git/status` | | | branch, change count, last commit |
| POST | `/internal/hourly-decision` | **header** `X-Crux-Secret` | `decision`: yes or no | `ok` |

**Speech endpoint auth:** v1 can be open on localhost only; if exposed beyond loopback, add Bearer token from env.

### 7.4 LLM router `server/llm/router.py`

- Order per `CRUX_LLM_PROVIDER`.
- **Exact cache** in Redis if enabled.
- **Semantic cache** in Postgres if enabled (see valid SQL below).
- On success persist row to `ai_generation_log` with embedding when available.

### 7.5 Semantic cache — **valid** SQL pattern

Do **not** use `HAVING` without `GROUP BY` incorrectly. Example pattern (implement in `cache.py` with parameters):

```sql
SELECT response_text,
       1 - (embedding <=> $1::vector) AS similarity
FROM ai_generation_log
WHERE (metadata->>'model_key') = $2
  AND created_at > NOW() - ($3::int * INTERVAL '1 day')
ORDER BY embedding <=> $1::vector
LIMIT 1;
```

Then in Python: if `similarity >= threshold`, return `response_text`; else miss.

### 7.6 Git modules

- **`ops.py`:** `asyncio.create_subprocess_exec` for `git` with cwd `CRUX_GIT_REPO_PATH` resolved to absolute path.
- **`review.py`:** Build Sentinel system prompt; return structured JSON or parse model output robustly.
- **`mr.py`:** `gh pr create` with env inheriting user login.

### 7.7 Daemons

| Daemon | Module | Persona key | Flag |
|--------|--------|-------------|------|
| Narrator | narrator.py | forge | CRUX_NARRATOR_ENABLED |
| Reviewer | reviewer.py | sentinel | CRUX_REVIEWER_ENABLED |
| Committer | committer.py | chronicle | CRUX_COMMITTER_ENABLED |
| Ambient | ambient.py | maestro | CRUX_AMBIENT_ENABLED |
| Watcher | watcher.py | echo | CRUX_WATCHER_ENABLED |

**Base class** `BaseDaemon`: `start`, `stop`, `health`, `speak(text, priority)`, internal `_safe_run` wrapper logging exceptions.

**`personas/registry.py`:** Default **Forge** `voice` must be **`en-US-JennyNeural`**, matching **`CruxSettings.CRUX_TTS_VOICE`**. Resolver applies `CRUX_FORGE_VOICE` / `CRUX_FORGE_RATE` overrides when set.

---

## 8. Part D — Hourly commit daemon (normative state machine)

Implement in `server/daemons/committer.py`.

```
States (conceptual):
  IDLE → (timer fires) → EVALUATE_DIRTY
  EVALUATE_DIRTY → if clean → SPEAK_CLEAN → IDLE
  EVALUATE_DIRTY → if dirty → SUMMARIZE → SPEAK_PROMPT → AWAIT_DECISION
  AWAIT_DECISION → on yes → FETCH_REBASE → (fail) → SPEAK_REBASE_FAIL → IDLE
  AWAIT_DECISION → on yes → FETCH_REBASE → (ok) → COMMIT_PUSH_MAYBE_MR → SPEAK_DONE → IDLE
  AWAIT_DECISION → on no → FETCH_REBASE → (fail) → SPEAK_REBASE_FAIL → IDLE
  AWAIT_DECISION → on no → FETCH_REBASE → (ok) → SPEAK_SKIPPED → IDLE
  AWAIT_DECISION → on timeout → DEFAULT_NO → if CRUX_HOURLY_REBASE_ON_TIMEOUT → FETCH_REBASE → … → IDLE
                                             else → SPEAK_TIMEOUT_NO → IDLE
```

**Shared behavior after explicit yes or no:**

1. Resolve `default_branch`: if `CRUX_GIT_TARGET_BRANCH` non-empty use it; else `gh repo view --json defaultBranchRef` or parse `git remote show origin`.
2. `git fetch origin`
3. `git rebase origin/<default_branch>`
4. On conflict: **do not** auto-commit; speak short message; log path e.g. `var/hourly-rebase-failure.log` with timestamp and branch; set internal metric or last_error visible in `/health` optional.

**Concurrency:** Use `asyncio.Event` or a small `HourlyDecisionBox` object mutated by `POST /internal/hourly-decision` and by STT task when listen enabled.

**Tests:** `tests/test_hourly_committer.py` uses temp git repo fixture.

---

## 9. Part E — TTS and audio

### Primary path

- `edge_tts.Communicate(text, voice, rate=..., pitch=...)`.
- **Streaming** (`CRUX_TTS_STREAM`): pipe PCM or MP3 chunks to `ffplay` stdin (implementers mirror proven approach in OpenClaw `friday-speak.py`).
- **Non-streaming:** write MP3 to `tempfile` with **`crux-tts`** in the name; play; delete.

### ffplay arguments (example)

```
ffplay -nodisp -autoexit -loglevel error -i pipe:0
```
or file input. Ensure process argv or window title is identifiable for selective kill.

### Text normalization

Strip or verbalize markdown and problematic symbols before synthesis (defense in depth with rule 050).

### Failure policy (no weak macOS `say` default)

- **CRUX_TTS_FALLBACK=none:** log error; optionally notify via **osascript display notification** only if you set fallback to **`notify`**.
- Do **not** use macOS `say` for Crux persona speech in v1 (voice mismatch).
- Optional future: Piper local TTS behind a separate flag and install doc.

### Shutdown

- `pkill -f 'ffplay.*crux-tts'` or track child PIDs in a process table guarded by lock.

---

## 10. Part F — Redis speaker lock

Keys:

- `crux:speaker:lock` — string value is **token** `"{pid}:{uuid8}"` with TTL `CRUX_TTS_LOCK_TTL_SEC`
- `crux:speaker:generation` — integer counter **INCR** on each speak request; playback task checks still current

**Acquire:**

- Loop sleep ~80ms until timeout.
- If `priority=true`: **DELETE** lock then **SET NX** (document preempt behavior).
- **Fail-open:** if Redis unavailable, optional file lock under `tempfile.gettempdir()` / `crux-speaker-active` with PID; check liveness with `os.kill(pid, 0)`.

**Release:** Lua script or GET + compare token + DEL to avoid stealing.

**Thinking lock (optional):** `crux:speaker:thinking` if you add thinking narration singleton.

---

## 11. Part G — Docker and SQL

### `docker/docker-compose.yml`

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    ports:
      - "127.0.0.1:5433:5432"
    environment:
      POSTGRES_USER: crux
      POSTGRES_PASSWORD: crux
      POSTGRES_DB: crux
    volumes:
      - crux_postgres:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U crux"]
      interval: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "127.0.0.1:6379:6379"
    command: redis-server --appendonly yes
    volumes:
      - crux_redis:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      retries: 5

volumes:
  crux_postgres:
  crux_redis:
```

**Security note:** Change passwords for any non-local shared environment.

### `docker/postgres/init/01-extensions.sql`

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### `docker/postgres/init/02-ai-cache.sql`

```sql
CREATE TABLE IF NOT EXISTS ai_generation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    prompt_hash TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    system_fingerprint TEXT,
    response_text TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    source TEXT,
    embedding vector(1536),
    input_tokens INT,
    output_tokens INT,
    latency_ms INT,
    cached BOOLEAN NOT NULL DEFAULT false,
    cache_hit_type TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_gen_log_created ON ai_generation_log USING brin (created_at);
CREATE INDEX IF NOT EXISTS idx_gen_log_embedding ON ai_generation_log USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_gen_log_prompt_hash ON ai_generation_log (prompt_hash);
CREATE INDEX IF NOT EXISTS idx_gen_log_metadata ON ai_generation_log USING gin (metadata);
```

---

## 12. Part H — Scripts and Makefile

### `scripts/setup.sh` (macOS)

```bash
#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Crux setup.sh supports macOS only."
  exit 1
fi

# Homebrew
if ! command -v brew >/dev/null 2>&1; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

brew update
brew install python@3.12 ffmpeg git gh curl jq || true

if ! command -v ffplay >/dev/null 2>&1; then
  echo "ffplay not found after ffmpeg install — check PATH."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Install Docker Desktop or Colima so docker compose works, then re-run."
  exit 1
fi

docker compose -f docker/docker-compose.yml up -d
# wait for postgres healthy (optional loop with docker inspect)

python3.12 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — edit secrets and CRUX_INTERNAL_SECRET."
fi

echo "Crux setup complete: activate .venv, set OPENROUTER_API_KEY, run make run."
```

### `scripts/speak.sh` (**safe JSON** — required)

```bash
#!/usr/bin/env bash
set -euo pipefail
TEXT="${1:?usage: speak.sh \"text\" [0|1]}"
PRIORITY="${2:-0}"
CRUX_PORT="${CRUX_PORT:-9090}"
if [[ "$PRIORITY" == "1" ]]; then PBOOL=true; else PBOOL=false; fi

jq -n --arg text "$TEXT" --argjson priority "$PBOOL" '{text:$text, priority:$priority}' \
  | curl -sS -X POST "http://127.0.0.1:${CRUX_PORT}/speak-async" \
      -H 'Content-Type: application/json' \
      -d @- >/dev/null &
```

Requires **`jq`** installed (setup.sh installs it).

### `scripts/clear-locks.sh`

```bash
#!/usr/bin/env bash
redis-cli DEL crux:speaker:lock crux:speaker:generation crux:speaker:thinking 2>/dev/null || true
rm -f "${TMPDIR:-/tmp}/crux-speaker-active" 2>/dev/null || true
echo "Crux locks cleared."
```

### `Makefile`

```makefile
.PHONY: setup run test speak docker-up docker-down clean

setup:
	bash scripts/setup.sh

run:
	. .venv/bin/activate && python -m server.main

test:
	. .venv/bin/activate && python -m pytest tests/ -x -q

speak:
	bash scripts/speak.sh "$(TEXT)" $(or $(P),0)

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

clean:
	bash scripts/clear-locks.sh
```

Run server from `crux/` root with venv activated; `PYTHONPATH` may need `.` — prefer `python -m server.main` with package layout fixed in `pyproject.toml`.

---

## 13. Part I — Environment template

Create `crux/.env.example` with **every** `CruxSettings` field and short comment for each. Mandatory highlights:

- `CRUX_ENABLED=true`
- `CRUX_INTERNAL_SECRET=` **generate random string for internal routes**
- `OPENROUTER_API_KEY=`
- `REDIS_URL=redis://127.0.0.1:6379`
- `DATABASE_URL=postgresql://crux:crux@127.0.0.1:5433/crux`
- `CRUX_GIT_REPO_PATH=` absolute path to git working copy Crux manages (often same as `crux/` or a parent app repo)
- `CRUX_TTS_VOICE=en-US-JennyNeural` — default **friendly** US assistant voice (same default as **Forge** in `registry.py`); document `CRUX_TTS_VOICE_BLOCK` for disallowed ids

---

## 14. Part J — Dependencies

### `requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.8.0
pydantic-settings>=2.4.0
openai>=1.40.0
anthropic>=0.40.0
edge-tts>=6.1.0
asyncpg>=0.29.0
pgvector>=0.3.0
redis>=5.0.0
watchdog>=4.0.0
structlog>=24.0.0
python-dotenv>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
ruff>=0.7.0
```

Optional extras (document in README — separate file or `pip install faster-whisper` when enabling `CRUX_LISTEN_ENABLED`).

### `pyproject.toml` (minimal sketch)

- `[project]` name `crux`, version `0.1.0`, Python `>=3.12`
- `[tool.ruff]` line length 100, target 3.12
- `[tool.pytest.ini_options]` asyncio mode auto

---

## 15. Part K — README and CONTRIBUTING expectations

**README.md** must include:

- What Crux is (one paragraph)
- macOS prerequisites
- Quick start: `make setup`, edit `.env`, `make docker-up`, `make run`, `make speak TEXT="hello"`
- Cursor: open `crux/` folder in Cursor so rules apply
- API table
- Troubleshooting: no ffplay, Redis down, Edge TTS 429, rebase conflicts

**CONTRIBUTING.md** must include:

- Conventional commits
- How to add a persona and resolver entry
- How to add a daemon and flag
- How to extend STT backend

**LICENSE:** MIT

---

## 16. Part L — Implementation order

1. `pyproject.toml`, `requirements.txt`, `.env.example`, `Makefile`, `docker/`
2. `server/config.py`
3. `server/db/redis_client.py`, `server/db/postgres.py`, SQL init
4. `server/tts/voices.py`, `lock.py`, `engine.py`, `speaker.py`
5. `server/personas/registry.py`, `resolver.py`
6. `server/llm/openrouter_client.py`, `claude_client.py`, `cache.py`, `router.py`
7. `server/git/ops.py`, `review.py`, `mr.py`
8. `server/daemons/base.py`, narrators, **committer** (hourly), and others
9. `server/routes/*` including `internal.py`
10. `server/main.py`
11. `scripts/setup.sh`, `speak.sh`, `clear-locks.sh`
12. `.cursor/rules` and `.cursor/skills`
13. `tests/`
14. `README.md`, `CONTRIBUTING.md`

---

## 17. Part M — Verification checklist

- `docker compose ps` healthy
- `curl -s http://127.0.0.1:9090/health`
- `make speak TEXT="hello world"` produces audio through default output device
- Two parallel speak requests serialize correctly; priority preempt works
- `/llm/chat` returns model output with `OPENROUTER_API_KEY` set
- Second identical prompt may show exact cache hit
- `/git/review` returns JSON on fixture diff
- Committer: force interval to 1 minute in test env; simulate yes, no, timeout, rebase conflict
- Ctrl+C stops ffplay children and clears Redis keys

---

## 18. Part N — Security and safety

- Bind **127.0.0.1** only unless user explicitly configures LAN exposure.
- Protect `/internal/hourly-decision` with `CRUX_INTERNAL_SECRET`.
- **Never** auto `git push --force`.
- Sanitize any user or model text before logging (avoid exfiltrating secrets from diffs in logs when possible).
- `.env` must never be committed.

---

## Appendix — OpenClaw reference code (read-only)

Implementers may **read** these files for patterns; **do not import** them from Crux at runtime:

- [`skill-gateway/scripts/friday-speak.py`](../skill-gateway/scripts/friday-speak.py) — Edge TTS + ffplay streaming, generation discard, volume quirks.
- [`skill-gateway/scripts/friday-play.py`](../skill-gateway/scripts/friday-play.py) — ffplay invocation patterns (music is out of scope for Crux v1).

---

**End of specification.** Creating the `crux/` tree is the next implementation phase after this document is accepted.
