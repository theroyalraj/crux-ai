#!/usr/bin/env bash
# Back-compat wrapper — see scripts/crux-service.sh for full CLI.
# Windows: pwsh scripts/restart.ps1 all | server  (full CLI: scripts/crux-service.ps1)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
case "${1:-}" in
  all) exec "$ROOT/scripts/crux-service.sh" restart-all ;;
  server) exec "$ROOT/scripts/crux-service.sh" restart-server ;;
  *)
    echo "usage: bash scripts/restart.sh all | server" >&2
    echo "  (delegates to scripts/crux-service.sh — see there for Terminal.app / start / stop)" >&2
    exit 1
    ;;
esac
