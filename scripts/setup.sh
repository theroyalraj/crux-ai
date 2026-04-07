#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Crux setup.sh supports macOS only."
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Install Homebrew first: https://brew.sh"
  exit 1
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

if ! command -v python3.12 >/dev/null 2>&1; then
  echo "python3.12 not found — brew install python@3.12"
  exit 1
fi

python3.12 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — edit secrets and CRUX_INTERNAL_SECRET."
fi

echo "Crux setup complete: activate .venv, set OPENROUTER_API_KEY, run make run."
