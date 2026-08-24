#!/usr/bin/env bash
# Clones (or updates) and compiles whisper.cpp with SDL2 support, which is
# what provides the `whisper-stream` real-time microphone binary.
#
# Safety notes:
#   - If ~/Developer/whisper.cpp already exists and has local changes,
#     this script does NOT run `git reset --hard`. It stops and asks you
#     to handle it manually, per the product spec's guardrails.
#   - Records the checked-out commit in docs/DECISIONS.md so the build is
#     reproducible / auditable later.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WHISPER_DIR="${WHISPER_DIR:-$HOME/Developer/whisper.cpp}"

echo "== Building whisper.cpp with SDL2 =="
echo "Target directory: $WHISPER_DIR"
echo "Command: git clone https://github.com/ggml-org/whisper.cpp.git"
echo "Reason : source for whisper-stream, the real-time transcription binary."
echo "Size   : repository is a few hundred MB with history."
echo "Network: yes, clones from GitHub."
echo "Remove : rm -rf \"$WHISPER_DIR\""
read -r -p "Proceed? [y/N] " reply
if [[ ! "$reply" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 1
fi

mkdir -p "$(dirname "$WHISPER_DIR")"

if [[ -d "$WHISPER_DIR/.git" ]]; then
  echo "Existing checkout found."
  if [[ -n "$(cd "$WHISPER_DIR" && git status --porcelain)" ]]; then
    echo "ERROR: $WHISPER_DIR has local changes. Refusing to touch it automatically."
    echo "Resolve manually (commit, stash, or move it aside) and re-run this script."
    exit 1
  fi
  echo "Updating existing checkout (git pull --ff-only)..."
  (cd "$WHISPER_DIR" && git pull --ff-only)
else
  git clone https://github.com/ggml-org/whisper.cpp.git "$WHISPER_DIR"
fi

COMMIT="$(cd "$WHISPER_DIR" && git rev-parse --short HEAD)"
echo "Checked out commit: $COMMIT"

echo "Configuring build (SDL2 ON) and compiling..."
(
  cd "$WHISPER_DIR"
  cmake -B build -DWHISPER_SDL2=ON
  cmake --build build -j --config Release
)

BINARY="$WHISPER_DIR/build/bin/whisper-stream"
if [[ ! -x "$BINARY" ]]; then
  echo "ERROR: build finished but $BINARY was not produced. Check the build log above."
  exit 1
fi

echo "Build OK: $BINARY"
"$BINARY" --help | head -n 20 || true

DECISIONS_FILE="$REPO_ROOT/docs/DECISIONS.md"
{
  echo ""
  echo "## whisper.cpp build — $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "- Repository: $WHISPER_DIR"
  echo "- Commit: $COMMIT"
  echo "- Build flags: -DWHISPER_SDL2=ON"
} >> "$DECISIONS_FILE"

echo "Recorded build info in docs/DECISIONS.md."
echo "Next: scripts/download_models.sh"
