#!/usr/bin/env bash
# Prepares this MacBook to run Local English Meeting Copilot.
#
# What this script does, in order, and why:
#   1. Verifies you are on Apple Silicon (arm64) macOS -- the whole
#      performance budget in the spec assumes Metal + arm64 whisper.cpp.
#   2. Verifies Xcode Command Line Tools are installed (needed to compile
#      whisper.cpp and for Homebrew itself).
#   3. Verifies Homebrew is installed (does NOT install it for you --
#      see the printed instructions, per the "confirm before installing"
#      rule in the product spec).
#   4. Installs git, cmake, sdl2, ffmpeg, python@3.11 via Homebrew, after
#      you confirm.
#   5. Creates a Python 3.11 virtual environment in .venv and installs
#      this project's Python dependencies.
#
# It does NOT clone/build whisper.cpp (scripts/build_whisper.sh) or
# download models (scripts/download_models.sh) -- those are separate,
# larger downloads and are kept as distinct, explicit steps.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Local English Meeting Copilot: bootstrap =="
echo

echo "[1/5] Checking architecture..."
ARCH="$(uname -m)"
if [[ "$ARCH" != "arm64" ]]; then
  echo "ERROR: expected arm64 (Apple Silicon), found '$ARCH'."
  echo "This project targets Apple M-series chips only."
  exit 1
fi
echo "  OK: arm64"

echo "[2/5] Checking Xcode Command Line Tools..."
if ! xcode-select -p >/dev/null 2>&1; then
  echo "  Command Line Tools not found."
  echo "  Command : xcode-select --install"
  echo "  Reason  : required to compile whisper.cpp and to run Homebrew."
  echo "  Size    : ~1-2 GB"
  echo "  Network : yes, downloads from Apple"
  echo "  Remove  : sudo rm -rf /Library/Developer/CommandLineTools"
  read -r -p "  Run 'xcode-select --install' now? [y/N] " reply
  if [[ "$reply" =~ ^[Yy]$ ]]; then
    xcode-select --install
    echo "  A system dialog should have opened. Re-run this script after it finishes."
    exit 0
  else
    echo "  Skipping. Re-run this script once Command Line Tools are installed."
    exit 1
  fi
fi
echo "  OK: Command Line Tools present"

echo "[3/5] Checking Homebrew..."
if ! command -v brew >/dev/null 2>&1; then
  echo "  Homebrew not found."
  echo "  This script will NOT install Homebrew automatically."
  echo "  Install it from the official site: https://brew.sh/"
  echo "  Do not use unofficial installers found in blog posts."
  exit 1
fi
echo "  OK: Homebrew present ($(brew --version | head -n1))"

echo "[4/5] Homebrew packages: git cmake sdl2 ffmpeg python@3.11"
echo "  Reason  : git/cmake/sdl2 build whisper.cpp; ffmpeg helps test audio; python@3.11 runs the backend."
echo "  Size    : roughly 300-500 MB combined (varies by what you already have)."
echo "  Network : yes, downloads from Homebrew's servers."
echo "  Remove  : brew uninstall git cmake sdl2 ffmpeg python@3.11"
read -r -p "  Run 'brew install git cmake sdl2 ffmpeg python@3.11' now? [y/N] " reply
if [[ "$reply" =~ ^[Yy]$ ]]; then
  brew update
  brew install git cmake sdl2 ffmpeg python@3.11
else
  echo "  Skipping package installation. The app will not run without these."
fi

echo
echo "  Versions:"
git --version || true
cmake --version | head -n1 || true
sdl2-config --version || true
ffmpeg -version | head -n1 || true
python3.11 --version || true

echo "[5/5] Python virtual environment (.venv)"
if [[ ! -d ".venv" ]]; then
  python3.11 -m venv .venv
  echo "  Created .venv"
else
  echo "  .venv already exists, reusing it"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
echo "  Installing Python dependencies from pyproject.toml (project + dev extras)..."
python -m pip install -e ".[dev]"

echo
echo "Bootstrap complete."
echo "Next steps:"
echo "  1. scripts/build_whisper.sh     # clone + compile whisper.cpp"
echo "  2. scripts/download_models.sh   # download small.en and pull the configured Ollama model"
echo "  3. scripts/doctor.sh            # verify everything is in place"
echo "  4. scripts/start.sh             # run the app"
