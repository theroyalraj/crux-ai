# Review

1. `git diff` (or range user asked for).
2. If health OK → pipe diff into **`POST /git/review`**: see **CONTRIBUTING.md** (`jq` + `curl` example).
3. Summarize findings in chat; offer fixes.
4. Optional voice: **`speak`** skill / `scripts/speak.sh` (plain English).
