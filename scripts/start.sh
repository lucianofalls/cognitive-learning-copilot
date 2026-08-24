#!/usr/bin/env bash
# Starts the app: activates .venv, does a quick Ollama warm-up, launches
# FastAPI/uvicorn bound to 127.0.0.1 only, and opens the browser.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -d ".venv" ]]; then
  echo "ERROR: .venv not found. Run scripts/bootstrap_macos.sh first."
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

HOST="127.0.0.1"
PORT="$(python -c "from meeting_copilot.config import load_settings; print(load_settings().server.port)" 2>/dev/null || echo 8000)"
# Was hardcoded to "qwen3:4b" -- silently warmed the wrong model (and never
# the configured one) every time config/settings.yaml's ollama.model changed.
OLLAMA_MODEL="$(python -c "from meeting_copilot.config import load_settings; print(load_settings().ollama.model)" 2>/dev/null || echo llama3.2:3b)"
# Translation can run on its own smaller/faster model (config/settings.yaml
# -> translation.model); empty means "same as ollama.model", already warmed
# above, so skip a redundant second warm-up call in that case.
TRANSLATION_MODEL="$(python -c "from meeting_copilot.config import load_settings; print(load_settings().translation.model)" 2>/dev/null || echo "")"

echo "Checking Ollama..."
if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "  Ollama is reachable. Warming up $OLLAMA_MODEL (short prompt)..."
  curl -s -X POST http://127.0.0.1:11434/api/generate \
    -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"Reply with the single word: ready\",\"stream\":false}" \
    >/dev/null || true
  if [[ -n "$TRANSLATION_MODEL" && "$TRANSLATION_MODEL" != "$OLLAMA_MODEL" ]]; then
    echo "  Warming up $TRANSLATION_MODEL (dedicated translation model)..."
    curl -s -X POST http://127.0.0.1:11434/api/generate \
      -d "{\"model\":\"$TRANSLATION_MODEL\",\"prompt\":\"Reply with the single word: ready\",\"stream\":false}" \
      >/dev/null || true
  fi
else
  echo "  WARNING: Ollama not reachable at 127.0.0.1:11434."
  echo "  The transcript will still work; coach suggestions will be paused"
  echo "  until Ollama is running (see docs/TROUBLESHOOTING.md)."
fi

echo "Starting server on http://$HOST:$PORT (loopback only)..."
( sleep 1.5 && command -v open >/dev/null 2>&1 && open "http://$HOST:$PORT" ) &

PYTHONPATH="$REPO_ROOT/src" python -m meeting_copilot.main
