# Merge request (MR) / pull request

1. **JIRA:** If the user did not give a JIRA issue key (e.g. `ABC-123`), **ask** for it before branching. Rule: **`.cursor/rules/023-mr-creation.mdc`**.
2. **Branch name:** `{type}/{JIRA-KEY}-{short-kebab-description}` — types: `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, `perf`, `ci` (bugs → `fix`). Example: `feat/CRUX-12-elevenlabs-tls`.
3. **Commit** on that branch (not on `main` if it is protected).
4. **`git push -u origin <branch>`** — do not rely on pushing to `main`.
5. **Open MR:** If **`/health`** OK → **`POST /git/mr`** with `title` / `body` / optional `base` (**`CONTRIBUTING.md`**). Else → **`gh pr create`** where applicable, or share the remote’s “create merge request” link.
6. Optional **`speak`** skill / **`scripts/speak.sh`**.
