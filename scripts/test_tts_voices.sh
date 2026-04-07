#!/usr/bin/env bash
# Verbose TTS sample per persona — all requests go through scripts/speak.sh (server serializes).
#
# Usage:
#   bash scripts/test_tts_voices.sh           # speak.sh --sync per persona (one after another)
#   bash scripts/test_tts_voices.sh --async    # speak.sh speak-async, priority 0 (queued on server)
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SPEAK="${ROOT}/scripts/speak.sh"
REG="${ROOT}/server/tts/data/tts_registry.json"
ASYNC=false
[[ "${1:-}" == "--async" ]] && ASYNC=true

curl -sf "${CRUX_BASE_URL:-http://127.0.0.1:9090}/health" >/dev/null || {
  echo "error: no server at ${CRUX_BASE_URL:-http://127.0.0.1:9090}" >&2
  exit 1
}

line_for_persona() {
  case "$1" in
    forge) echo "Forge persona. Chief architect voice. This is a longer sample so you can judge pacing, clarity, and warmth across several sentences. Crux is reading registry defaults for United States English." ;;
    sentinel) echo "Sentinel persona. Code guardian. This sample uses a steadier male-leaning chain. Listen for articulation and whether warnings would sound credible. End of Sentinel block." ;;
    chronicle) echo "Chronicle persona. Release engineer. British locale chain here. The voice should feel suited to changelogs, merges, and shipping talk. Thank you for listening to Chronicle." ;;
    sage) echo "Sage persona. Research analyst. Slightly slower delivery is configured. This block is meant for explanations and careful reasoning. Sage sample complete." ;;
    maestro) echo "Maestro persona. Operations lead. Friendly operations tone for reminders and pacing. A few sentences bundled so you can compare against forge and sage. Maestro done." ;;
    echo) echo "Echo persona. Context keeper. Irish edge with Moira on say when available. This should sound distinct from pure British or American defaults. Echo block finished." ;;
    priya) echo "Priya persona. Hindi edge voice path. Namaste. This line mixes English framing with the Hindi neural profile so you can hear how Crux handles this locale." ;;
    siri) echo "Siri persona. System assistant style with Aman on say when present, otherwise edge assistant voice. This is the Siri-style sample in the voice pool tour." ;;
    *) echo "Persona ${1}. Verbose default sample line one. Line two for pacing. Line three goodbye." ;;
  esac
}

echo "Using ${SPEAK} ($([[ "$ASYNC" == true ]] && echo async || echo sync))"
n=0
while IFS= read -r p; do
  n=$((n + 1))
  msg="$(line_for_persona "$p")"
  if [[ "$ASYNC" == true ]]; then
    # priority 0: queue on server without preempting previous non-priority playback
    bash "$SPEAK" "$msg" 0 "$p"
    echo " -> queued ${p}"
    sleep 0.3
  else
    echo "playing ${p} (sync)..."
    bash "$SPEAK" --sync "$msg" 0 "$p"
    echo " -> ok ${p}"
  fi
done < <(jq -r '.personas | keys[]' "$REG" | sort)
echo "Done. ${n} personas."
