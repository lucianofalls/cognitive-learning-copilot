#!/usr/bin/env bash
# Verifies the machine is ready to run the app and prints a checklist,
# matching section 24 of the product spec. Never modifies anything.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WHISPER_DIR="${WHISPER_DIR:-$HOME/Developer/whisper.cpp}"
WHISPER_BIN="$WHISPER_DIR/build/bin/whisper-stream"
WHISPER_MODEL="$WHISPER_DIR/models/ggml-small.en.bin"

PASS=0
FAIL=0

check() {
  local label="$1"
  local ok="$2"
  if [[ "$ok" == "0" ]]; then
    echo "[OK] $label"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] $label"
    FAIL=$((FAIL + 1))
  fi
}

ARCH="$(uname -m)"
[[ "$ARCH" == "arm64" ]]; check "architecture arm64" $?

sw_vers >/dev/null 2>&1; check "macOS supported" $?

if [[ -x ".venv/bin/python3.11" ]]; then
  check "Python 3.11 (in .venv)" 0
  # Read the actually-configured model instead of a hardcoded name -- this
  # used to check for a literal "qwen3:4b", which stayed stale (and always
  # FAILed) after ollama.model was switched to llama3.2:3b on 2026-07-17.
  # See docs/DECISIONS.md, 2026-07-20 "stale hardcoded model in a script".
  OLLAMA_MODEL="$(PYTHONPATH="$REPO_ROOT/src" .venv/bin/python3.11 -c "from meeting_copilot.config import load_settings; print(load_settings().ollama.model)" 2>/dev/null || echo llama3.2:3b)"
elif command -v python3.11 >/dev/null 2>&1; then
  check "Python 3.11 (on PATH)" 0
  OLLAMA_MODEL="llama3.2:3b"
else
  check "Python 3.11" 1
  OLLAMA_MODEL="llama3.2:3b"
fi

if command -v ollama >/dev/null 2>&1; then
  curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1
  check "Ollama API reachable at 127.0.0.1:11434" $?

  ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"
  check "$OLLAMA_MODEL installed" $?
else
  check "Ollama API reachable at 127.0.0.1:11434" 1
  check "$OLLAMA_MODEL installed" 1
fi

[[ -x "$WHISPER_BIN" ]]; check "whisper-stream binary ($WHISPER_BIN)" $?
[[ -f "$WHISPER_MODEL" ]]; check "ggml-small.en.bin ($WHISPER_MODEL)" $?

# Microphone permission cannot be checked headlessly and reliably; this is
# a best-effort hint, not a hard pass/fail.
echo "[INFO] microphone permission: grant it to your terminal app in"
echo "       System Settings > Privacy & Security > Microphone the first"
echo "       time whisper-stream runs."

if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  check "port 8000 available" 1
else
  check "port 8000 available" 0
fi

if lsof -iTCP:11434 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[OK] port 11434 in use (expected: Ollama should be running)"
  PASS=$((PASS + 1))
else
  check "port 11434 available (Ollama not yet running)" 0
fi

if [[ -f "config/settings.yaml" && -f "config/glossary.yaml" ]]; then
  check "configuration files present" 0
else
  check "configuration files present" 1
fi

if [[ -f "config/profile.yaml" ]]; then
  check "config/profile.yaml exists" 0
else
  check "config/profile.yaml exists" 1
  echo "       Copy config/profile.example.yaml to config/profile.yaml and fill in your own name/role/expertise."
fi

echo
echo "Summary: $PASS passed, $FAIL failed."
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
