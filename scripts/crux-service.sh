#!/usr/bin/env bash
# Crux process control: Docker deps + API server.
#
# Why Terminal.app for "start-*-terminal"?
#   Cursor’s integrated runner/sandbox often cannot use macOS audio (say / ffplay).
#   Starting the server in Terminal.app ties the process to a normal login session.
#
# Usage (from repo root):
#   bash scripts/crux-service.sh stop-server
#   bash scripts/crux-service.sh start-server
#   bash scripts/crux-service.sh start-server-terminal
#   bash scripts/crux-service.sh start-all
#   bash scripts/crux-service.sh start-all-terminal
#   bash scripts/crux-service.sh restart-server
#   bash scripts/crux-service.sh restart-all
#   bash scripts/crux-service.sh restart-server-terminal
#   bash scripts/crux-service.sh restart-all-terminal
#   bash scripts/crux-service.sh status
#   bash scripts/crux-service.sh docker-up | docker-down | docker-restart
#
# Env: CRUX_PORT (default 9090), COMPOSE_FILE (default docker/docker-compose.yml)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/docker/docker-compose.yml}"
CRUX_PORT="${CRUX_PORT:-9090}"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/crux-server.log"
PID_FILE="$LOG_DIR/crux-server.pid"

cd "$ROOT"

usage() {
  cat >&2 <<'EOF'
Crux service control (run from repo root, ideally in Terminal.app for TTS/audio):

  stop-server              Stop API on CRUX_PORT (default 9090)
  stop-all                 stop-server + docker compose down
  start-server             Start API in background (logs/crux-server.log)
  start-server-terminal    Open Terminal.app and run API in foreground (best for speech)
  start-server-fg          Foreground API (used by start-server-terminal)
  start-all                docker up -d + start-server
  start-all-terminal       docker up + start in Terminal.app
  restart-server           stop-server + start-server
  restart-all              docker restart + stop-server + start-server
  restart-server-terminal  stop + foreground in new Terminal window
  restart-all-terminal     docker restart + stop + Terminal foreground
  docker-up | docker-down | docker-restart
  status                   health curl, port, compose ps
EOF
  exit 1
}

kill_listener_on_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    echo "no process listening on ${port}"
    rm -f "$PID_FILE" 2>/dev/null || true
    return 0
  fi
  echo "stopping PID(s) on port ${port}: ${pids}"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 0.5
  pids="$(lsof -ti "tcp:${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
  fi
  rm -f "$PID_FILE" 2>/dev/null || true
}

require_venv() {
  if [[ ! -d "$ROOT/.venv" ]]; then
    echo "error: .venv missing — run: make setup" >&2
    exit 1
  fi
}

wait_for_health() {
  local i
  for i in $(seq 1 40); do
    if curl -sf "http://127.0.0.1:${CRUX_PORT}/health" >/dev/null 2>&1; then
      echo "ok: http://127.0.0.1:${CRUX_PORT}/health"
      return 0
    fi
    sleep 0.25
  done
  echo "warning: health check timed out (server may still be starting) — tail -f ${LOG_FILE}" >&2
  return 1
}

cmd_start_server_fg() {
  require_venv
  mkdir -p "$LOG_DIR"
  # shellcheck disable=SC1091
  source .venv/bin/activate
  export CRUX_PORT
  exec python -m server.main
}

cmd_start_server() {
  require_venv
  if lsof -ti "tcp:${CRUX_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "already listening on ${CRUX_PORT} — use stop-server first or pick another CRUX_PORT" >&2
    exit 1
  fi
  mkdir -p "$LOG_DIR"
  echo "starting Crux in background → ${LOG_FILE}"
  (
    # shellcheck disable=SC1091
    source .venv/bin/activate
    export CRUX_PORT
    exec python -m server.main
  ) >>"$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" >"$PID_FILE"
  echo "PID ${pid}"
  wait_for_health || true
}

cmd_start_server_terminal() {
  require_venv
  local qroot
  qroot=$(printf %q "$ROOT")
  osascript \
    -e 'tell application "Terminal"' \
    -e '  activate' \
    -e "  do script \"cd ${qroot} && export CRUX_PORT=${CRUX_PORT} && bash scripts/crux-service.sh start-server-fg\"" \
    -e 'end tell' 2>/dev/null || {
    echo "error: could not open Terminal.app — run in Terminal: cd $ROOT && make run" >&2
    exit 1
  }
  echo "opened new Terminal window — server runs in foreground there (Ctrl+C to stop)"
}

cmd_docker_up() {
  [[ -f "$COMPOSE_FILE" ]] || { echo "missing: $COMPOSE_FILE" >&2; exit 1; }
  docker compose -f "$COMPOSE_FILE" up -d
}

cmd_docker_down() {
  [[ -f "$COMPOSE_FILE" ]] || { echo "missing: $COMPOSE_FILE" >&2; exit 1; }
  docker compose -f "$COMPOSE_FILE" down
}

cmd_docker_restart() {
  [[ -f "$COMPOSE_FILE" ]] || { echo "missing: $COMPOSE_FILE" >&2; exit 1; }
  docker compose -f "$COMPOSE_FILE" restart
}

cmd_start_all() {
  cmd_docker_up
  cmd_start_server
}

cmd_start_all_terminal() {
  cmd_docker_up
  cmd_start_server_terminal
}

cmd_restart_server() {
  kill_listener_on_port "$CRUX_PORT"
  cmd_start_server
}

cmd_restart_all() {
  cmd_docker_restart
  kill_listener_on_port "$CRUX_PORT"
  cmd_start_server
}

cmd_restart_server_terminal() {
  kill_listener_on_port "$CRUX_PORT"
  cmd_start_server_terminal
}

cmd_restart_all_terminal() {
  cmd_docker_restart
  kill_listener_on_port "$CRUX_PORT"
  cmd_start_server_terminal
}

cmd_stop_all() {
  kill_listener_on_port "$CRUX_PORT"
  cmd_docker_down
}

cmd_status() {
  echo "CRUX_PORT=${CRUX_PORT}"
  if curl -sf "http://127.0.0.1:${CRUX_PORT}/health" 2>/dev/null; then
    echo ""
  else
    echo "health: (no response)"
  fi
  echo "--- listen ---"
  lsof -nP -iTCP:"${CRUX_PORT}" -sTCP:LISTEN 2>/dev/null || echo "(nothing on ${CRUX_PORT})"
  echo "--- docker (compose file) ---"
  if [[ -f "$COMPOSE_FILE" ]]; then
    docker compose -f "$COMPOSE_FILE" ps 2>/dev/null || echo "(docker not running or no containers)"
  else
    echo "no compose file"
  fi
  [[ -f "$PID_FILE" ]] && echo "--- pid file --- $(cat "$PID_FILE")"
}

CMD="${1:-}"
case "$CMD" in
  stop-server)
    kill_listener_on_port "$CRUX_PORT"
    ;;
  stop-all)
    cmd_stop_all
    ;;
  start-server-fg)
    cmd_start_server_fg
    ;;
  start-server)
    cmd_start_server
    ;;
  start-server-terminal)
    cmd_start_server_terminal
    ;;
  docker-up) cmd_docker_up ;;
  docker-down) cmd_docker_down ;;
  docker-restart) cmd_docker_restart ;;
  start-all) cmd_start_all ;;
  start-all-terminal) cmd_start_all_terminal ;;
  restart-server) cmd_restart_server ;;
  restart-all) cmd_restart_all ;;
  restart-server-terminal) cmd_restart_server_terminal ;;
  restart-all-terminal) cmd_restart_all_terminal ;;
  status) cmd_status ;;
  help|-h|--help|"")
    usage
    ;;
  *)
    echo "unknown command: $CMD" >&2
    usage
    ;;
esac
