#!/usr/bin/env bash
# Downloads the two models this project needs:
#   1. whisper.cpp's ggml-small.en.bin       (~465 MB, English-only Whisper small)
#   2. Whatever Ollama model config/settings.yaml's ollama.model names
#      (llama3.2:3b by default, ~2 GB, Q4_K_M quantization)
#
# Both downloads require internet access and are confirmed individually
# before running, per the product spec's "confirm before downloading" rule.
#
# The Ollama model name is read from config/settings.yaml at run time, not
# hardcoded -- a previous version of this script hardcoded "qwen3:4b" and
# silently went stale when ollama.model was switched to llama3.2:3b on
# 2026-07-17, so a fresh bootstrap would have pulled a model the app was
# never going to use. See scripts/start.sh's OLLAMA_MODEL for the same
# pattern, fixed the same way, earlier.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_DIR="${WHISPER_DIR:-$HOME/Developer/whisper.cpp}"

if [[ ! -d "$REPO_ROOT/.venv" ]]; then
  echo "ERROR: .venv not found. Run scripts/bootstrap_macos.sh first."
  exit 1
fi
# shellcheck disable=SC1091
source "$REPO_ROOT/.venv/bin/activate"
OLLAMA_MODEL="$(PYTHONPATH="$REPO_ROOT/src" python -c "from meeting_copilot.config import load_settings; print(load_settings().ollama.model)" 2>/dev/null || echo llama3.2:3b)"

echo "== Downloading models =="

echo
echo "[1/2] Whisper model: small.en"
echo "Command: sh ./models/download-ggml-model.sh small.en   (run inside $WHISPER_DIR)"
echo "Reason : English-only transcription model used by whisper-stream."
echo "Size   : approximately 465 MB"
echo "Network: yes, downloads from Hugging Face / ggerganov's model mirror."
echo "Remove : rm \"$WHISPER_DIR/models/ggml-small.en.bin\""
if [[ ! -d "$WHISPER_DIR" ]]; then
  echo "ERROR: $WHISPER_DIR not found. Run scripts/build_whisper.sh first."
  exit 1
fi
read -r -p "Download small.en now? [y/N] " reply
if [[ "$reply" =~ ^[Yy]$ ]]; then
  (cd "$WHISPER_DIR" && sh ./models/download-ggml-model.sh small.en)
else
  echo "Skipped."
fi

echo
echo "[2/2] Ollama model: $OLLAMA_MODEL"
echo "Command: ollama pull $OLLAMA_MODEL"
echo "Reason : local LLM used for context explanation and phrase suggestions."
echo "Size   : a few GB depending on the model, Q4_K_M quantization by default."
echo "Network: yes, downloads from Ollama's model registry."
echo "Remove : ollama rm $OLLAMA_MODEL"
if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: 'ollama' command not found."
  echo "Install Ollama first from https://ollama.com/download, then re-run this script."
  exit 1
fi
read -r -p "Run 'ollama pull $OLLAMA_MODEL' now? [y/N] " reply
if [[ "$reply" =~ ^[Yy]$ ]]; then
  ollama pull "$OLLAMA_MODEL"
else
  echo "Skipped."
fi

echo
echo "Verifying..."
if [[ -f "$WHISPER_DIR/models/ggml-small.en.bin" ]]; then
  echo "  OK: ggml-small.en.bin present ($(du -h "$WHISPER_DIR/models/ggml-small.en.bin" | cut -f1))"
else
  echo "  MISSING: ggml-small.en.bin"
fi

if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
  echo "  OK: $OLLAMA_MODEL present in 'ollama list'"
else
  echo "  MISSING: $OLLAMA_MODEL"
fi

echo
echo "Next: scripts/doctor.sh"
