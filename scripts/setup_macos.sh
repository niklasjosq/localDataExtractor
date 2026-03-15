#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/5] Checking Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required: https://brew.sh" >&2
  exit 1
fi

echo "[2/5] Installing native dependencies"
brew install tesseract ocrmypdf poppler openjdk || true
brew install --cask libreoffice || true

echo "[3/5] Ensuring uv is available"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "[4/5] Creating virtual environment and installing Python packages"
uv venv .venv
source .venv/bin/activate
uv pip install -e .[full,dev]

echo "[5/5] Writing sample config if missing"
if [[ ! -f config.toml ]]; then
  cp config.sample.toml config.toml
fi

cat <<'MSG'
Setup complete.

Next:
1) Start LM Studio local server at http://localhost:1234/v1
2) localdataextractor --config config.toml check-llm
3) localdataextractor --config config.toml ingest <input> <output> --explain-route
4) localdataextractor-gui
MSG
