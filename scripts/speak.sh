#!/usr/bin/env bash
# Single client path to Crux speech — always hits the server (no local say).
# Foreground curl so callers chain naturally; server serializes playback via lock + generation rules.
#
# Usage:
#   bash scripts/speak.sh "Plain English text" [priority 0|1] [persona]
#   bash scripts/speak.sh --sync "text" [0|1] [persona]    # POST /speak, wait for playback
#
# Env: CRUX_BASE_URL (default http://127.0.0.1:9090)
#
set -euo pipefail
SYNC=false
if [[ "${1:-}" == "--sync" ]]; then
  SYNC=true
  shift
fi
TEXT="${1:?usage: speak.sh [--sync] \"text\" [priority 0|1] [persona]}"
PRIORITY="${2:-0}"
PERSONA="${3:-}"
B="${CRUX_BASE_URL:-http://127.0.0.1:9090}"
if [[ "$PRIORITY" == "1" ]]; then PBOOL=true; else PBOOL=false; fi

if [[ -n "$PERSONA" ]]; then
  payload=$(jq -n --arg text "$TEXT" --argjson priority "$PBOOL" --arg persona "$PERSONA" \
    '{text:$text, priority:$priority, persona:$persona}')
else
  payload=$(jq -n --arg text "$TEXT" --argjson priority "$PBOOL" '{text:$text, priority:$priority}')
fi

if [[ "$SYNC" == true ]]; then
  echo "$payload" | curl -sS -m 300 -X POST "${B}/speak" -H 'Content-Type: application/json' -d @-
else
  echo "$payload" | curl -sS -X POST "${B}/speak-async" -H 'Content-Type: application/json' -d @-
fi
echo ""
