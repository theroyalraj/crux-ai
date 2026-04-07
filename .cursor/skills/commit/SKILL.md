# Commit

1. **`CONTRIBUTING.md`** — run local checks (`make test` / ruff / pytest as documented).
2. `git status` / `git diff`; stop if empty (unless user wants otherwise).
3. If **`curl -sf "${CRUX_BASE_URL:-http://127.0.0.1:9090}/health"`** → `POST /git/commit` with `{"message":"type(scope): subject"}` (see **CONTRIBUTING.md** Conventional Commits). Optional: `POST /llm/chat` to draft the message.
4. Else → local `git add` / `git commit`.
5. Voice: **`speak`** skill — `bash scripts/speak.sh "…" 1` (or `0` to queue) after commit; plain English per **`000`** / **`050`**.
