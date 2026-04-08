# Speak (Crux TTS)

**This is the only path agents should use to produce voice.** It always calls the Crux server (or tries to).

## Command

**Unix / Git Bash:** use bash (requires `jq` on PATH, same as before):

```bash
bash scripts/speak.sh "Plain English only, no symbols" [priority] [persona]
```

**Windows PowerShell:** use `scripts/speak.ps1` (uses `curl.exe`, no bash, no `jq`). **Do not use `cd ... && ...` on PowerShell 5.x** — `&&` is invalid; chain with `;` instead.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/speak.ps1 "Plain English only, no symbols" [priority] [persona]
```

Example from repo root:

```powershell
cd d:\code\crux-ai; powershell -NoProfile -ExecutionPolicy Bypass -File scripts\speak.ps1 "Hello" 1
```

- **priority:** `0` = queue with other speech (default). `1` = preempt current speech.
- **persona:** optional — `forge`, `sentinel`, `chronicle`, `sage`, `maestro`, `echo`, `priya`, `siri` (see **CONTRIBUTING.md**).

Wait for playback to finish before ending the turn:

```bash
bash scripts/speak.sh --sync "Your closing summary here" 1
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/speak.ps1 --sync "Your closing summary here" 1
```

## Rules

- **`050-no-markdown-in-speech`** — spoken strings must be plain English.
- **`000-agent-http.mdc`** — voice table (start, major change, end, blocked).
- **`010-acknowledge-before-planning.mdc`** — ack before work; batch **`speak.sh`** with first tool calls.
- **`015-agent-speak-mandatory.mdc`** — mandatory spoken ack and completion; **never skip `speak.sh` because `/health` failed**.
- Use **`curl`** for non-speak APIs per **CONTRIBUTING.md**; do not hand-roll **`curl`** to `/speak` for routine narration.
- Do not call **`say`**, **`afplay`**, or local TTS.

## Health

You are **not** responsible for server uptime. **Always run `speak.sh` when the rules require it.** If **`curl`** fails, note it in chat if relevant; do not use that as a reason to skip voice attempts.

## Env

`CRUX_BASE_URL` if the server is not on `http://127.0.0.1:9090`.
