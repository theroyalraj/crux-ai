# Hourly report

1. `git log --since="1 hour ago" --oneline`; `git diff --stat`.
2. If health OK → optional **`POST /llm/chat`** for narrative; optional **`speak`** skill for voice.
3. Dirty tree → offer commit/MR (**commit** / **mr** skills).
4. **`POST /internal/hourly-decision`** only with **`X-Crux-Secret`** already in the environment (**CONTRIBUTING.md**).
