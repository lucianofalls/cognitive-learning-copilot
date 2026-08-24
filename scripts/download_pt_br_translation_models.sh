#!/usr/bin/env bash
# Downloads and converts the two OPUS-MT models context/opus_mt.py needs:
#   1. Helsinki-NLP/opus-mt-tc-big-en-pt  (EN->PT-BR, ~229 MB after int8 conversion)
#   2. Helsinki-NLP/opus-mt-ROMANCE-en    (PT->EN,    ~80 MB after int8 conversion)
#
# Fixes a real dialect bug: argostranslate's only en->pt package is
# European Portuguese, not Brazilian -- confirmed empirically 2026-07-22.
# See docs/DECISIONS.md and context/opus_mt.py's module docstring.
#
# Conversion needs transformers+torch (to load the original PyTorch
# weights), but the *running app* never imports those -- only
# ctranslate2 + sentencepiece at runtime, both already installed as
# transitive deps of argostranslate. So conversion happens in a
# throwaway venv here, matching this project's "convert once, run
# light" precedent (same shape as whisper.cpp's own model download).
#
# Requires internet access. Confirmed before each download, per the
# product spec's "confirm before downloading" rule (same as
# scripts/download_models.sh).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="${OPUS_MT_MODELS_DIR:-$HOME/Developer/opus-mt-models}"
PYTHON311="/opt/homebrew/opt/python@3.11/bin/python3.11"

if [[ ! -x "$PYTHON311" ]]; then
  echo "ERROR: $PYTHON311 not found. This script needs the same Python 3.11"
  echo "the project's own .venv uses -- the ambient 'python3' on PATH may be"
  echo "too old (e.g. 3.6) for modern torch/transformers wheels."
  exit 1
fi

CONVERT_VENV="$(mktemp -d)/convert_venv"
cleanup() {
  rm -rf "$CONVERT_VENV"
}
trap cleanup EXIT

echo "== Setting up a throwaway venv for conversion only =="
"$PYTHON311" -m venv "$CONVERT_VENV"
# shellcheck disable=SC1091
source "$CONVERT_VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet transformers torch sentencepiece ctranslate2

convert_model() {
  local hf_model="$1"
  local output_dir="$2"
  local description="$3"

  echo
  echo "== $description =="
  echo "Model  : $hf_model"
  echo "Output : $output_dir"
  echo "Network: yes, downloads from Hugging Face."
  echo "Remove : rm -rf \"$output_dir\""
  if [[ -d "$output_dir" ]]; then
    echo "Already exists -- skipping. Delete the directory first to reconvert."
    return
  fi
  read -r -p "Download and convert now? [y/N] " reply
  if [[ ! "$reply" =~ ^[Yy]$ ]]; then
    echo "Skipped."
    return
  fi
  ct2-transformers-converter \
    --model "$hf_model" \
    --output_dir "$output_dir" \
    --quantization int8 \
    --copy_files source.spm target.spm vocab.json
}

mkdir -p "$MODELS_DIR"

convert_model \
  "Helsinki-NLP/opus-mt-tc-big-en-pt" \
  "$MODELS_DIR/en-pt-br" \
  "[1/2] EN->PT-BR (Brazilian Portuguese via >>pob<< tag)"

convert_model \
  "Helsinki-NLP/opus-mt-ROMANCE-en" \
  "$MODELS_DIR/pt-en" \
  "[2/2] PT->EN (source-multilingual, no tag needed)"

echo
echo "Verifying..."
for dir in "$MODELS_DIR/en-pt-br" "$MODELS_DIR/pt-en"; do
  if [[ -f "$dir/model.bin" ]]; then
    echo "  OK: $dir ($(du -h "$dir/model.bin" | cut -f1))"
  else
    echo "  MISSING: $dir"
  fi
done

echo
echo "Set translation.engine: opus_mt in config/settings.yaml to use these."
echo "Default paths match config.py's TranslationSettings defaults --"
echo "only set opus_mt_en_pt_dir/opus_mt_pt_en_dir there if you used"
echo "OPUS_MT_MODELS_DIR to put them somewhere else."
