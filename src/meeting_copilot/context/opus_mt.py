"""EN<->PT-BR translation via Helsinki-NLP OPUS-MT models (CTranslate2).

Fixes a real dialect bug in `argos_translate.py`: argostranslate's only
`en->pt` package is European Portuguese, not Brazilian -- confirmed
empirically 2026-07-22 (e.g. "Devias ligar-me" / "boleia" / "casa de
banho" / "comboio" / "equipa" -- all PT-PT, none of them what a
Brazilian would say). See docs/DECISIONS.md.

Two independent models, each converted once (int8, see
scripts/download_pt_br_translation_models.sh) from PyTorch/transformers
to CTranslate2 -- the same inference engine argostranslate already uses
under the hood, so this adds no new *runtime* dependency (`ctranslate2`
and `sentencepiece` are already installed transitively via
argostranslate). `transformers`/`torch` are only ever needed for the
one-time conversion step, never imported here.

- EN->PT-BR: `Helsinki-NLP/opus-mt-tc-big-en-pt`, CC-BY-4.0. Needs the
  `>>pob<<` target-variant tag (confirmed via the model's vocab.json --
  `>>por<<` is European, `>>pob<<` is Brazilian; these are NOT part of
  the sentencepiece vocabulary, they're separately-added special tokens,
  so they must be prepended as an already-tokenized piece, never run
  through `sp.encode()` -- doing that produces garbage, confirmed
  empirically).
- PT->EN: `Helsinki-NLP/opus-mt-ROMANCE-en`, Apache-2.0, source-
  multilingual (many Romance languages -> English), no target tag
  needed (its vocab.json has no `>>xx<<` entries at all).

Both models need an explicit trailing `</s>` appended to the *source*
token sequence -- `transformers`' MarianTokenizer adds this
automatically, but calling ctranslate2 + sentencepiece directly does
not. Omitting it reproduces a real degenerate-repetition failure mode
(confirmed empirically: even a plain English sentence through the PT->EN
model looped indefinitely without it) -- this isn't a translation-
quality tuning knob, it's a required input format detail.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from pathlib import Path

from meeting_copilot.logging_config import log_event

logger = logging.getLogger(__name__)

_PAUSE_MARKER_RE = re.compile(r"\[pausa:\s*[\d.,]+\s*s\]", re.IGNORECASE)

# Safety net for _protect_and_translate's placeholder tokens (see there):
# confirmed 2026-08-12 that "ZZPROTECTEDZZ{n}ZZ" does NOT reliably survive
# SentencePiece tokenization + beam search intact -- a real session leaked
# "ZZPROTECTEDZ0ZZ" (one Z short of the real token) straight into the
# PT-BR shown to the user. The digit run in the middle survives far more
# reliably than the letter run around it (numbers rarely get merged into
# neighboring subword pieces the way repeated capital letters do), so this
# matches on a loosely-spelled token and recovers the original text via
# that digit -- exact Z-count no longer required. If even the digit is
# gone, there's nothing left to recover from -- fall back to a visible
# placeholder instead of leaking the raw internal token into the UI.
_LEFTOVER_PROTECTED_TOKEN_RE = re.compile(r"Z{1,4}\s*PROTECTED\s*Z{0,4}\s*(\d+)\s*Z{0,4}", re.IGNORECASE)
_UNRECOVERABLE_PLACEHOLDER = "[não traduzido]"

# Empirically tuned (2026-07-22) against both models: no_repeat_ngram_size
# alone wasn't enough to stop occasional single-word duplication on short
# sentences; this combination produced clean output across ~10 real test
# sentences per direction.
_BEAM_SIZE = 4
_NO_REPEAT_NGRAM_SIZE = 3
_REPETITION_PENALTY = 1.15


class _OpusModel:
    """Thread-safe lazy-loaded CTranslate2 translator + its two SentencePiece
    tokenizers. One instance per direction -- mirrors argos_translate.py's
    load-once-per-process pattern, generalized since there are two models
    here instead of one.
    """

    def __init__(self, model_dir: Path, target_tag: str | None) -> None:
        self._model_dir = model_dir
        self._target_tag = target_tag
        self._lock = threading.Lock()
        self._loaded = False
        self._translator = None
        self._sp_source = None
        self._sp_target = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            import ctranslate2
            import sentencepiece as spm

            if not self._model_dir.exists():
                raise FileNotFoundError(
                    f"OPUS-MT model not found at {self._model_dir}. "
                    "Run scripts/download_pt_br_translation_models.sh."
                )
            self._translator = ctranslate2.Translator(str(self._model_dir), device="cpu")
            self._sp_source = spm.SentencePieceProcessor(model_file=str(self._model_dir / "source.spm"))
            self._sp_target = spm.SentencePieceProcessor(model_file=str(self._model_dir / "target.spm"))
            self._loaded = True
            log_event(logger, "opus_mt", "model_ready", model_dir=str(self._model_dir))

    def translate(self, text: str) -> str:
        """Runs on a worker thread -- ctranslate2 is synchronous/CPU-bound."""
        self._ensure_loaded()
        assert self._translator is not None and self._sp_source is not None and self._sp_target is not None

        tokens = list(self._sp_source.encode(text, out_type=str))
        if self._target_tag:
            tokens = [self._target_tag] + tokens
        tokens = tokens + ["</s>"]

        result = self._translator.translate_batch(
            [tokens],
            beam_size=_BEAM_SIZE,
            no_repeat_ngram_size=_NO_REPEAT_NGRAM_SIZE,
            repetition_penalty=_REPETITION_PENALTY,
            max_decoding_length=len(tokens) * 3 + 10,
        )
        return self._sp_target.decode(result[0].hypotheses[0])


def _protect_and_translate(model: _OpusModel, text: str, glossary_terms: tuple[str, ...]) -> str:
    # Pause markers and glossary terms aren't in the NMT model's training
    # data -- protect them with plain-ASCII placeholders (same approach as
    # argos_translate.py) and restore them afterward instead of trusting
    # the model with them. The exact-token replace below is the common
    # case; _LEFTOVER_PROTECTED_TOKEN_RE right after it is the safety net
    # for when the model doesn't preserve the token intact (see that
    # regex's comment) -- exact match first because it's a plain string
    # replace, cheaper and unambiguous when it works.
    protected: dict[str, str] = {}

    def protect(original: str) -> str:
        token = f"ZZPROTECTEDZZ{len(protected)}ZZ"
        protected[token] = original
        return token

    working = _PAUSE_MARKER_RE.sub(lambda m: protect(m.group(0)), text)
    for term in glossary_terms:
        if term and term in working:
            working = working.replace(term, protect(term))

    translated = model.translate(working)

    for token, original in protected.items():
        translated = translated.replace(token, original)

    def _resolve_leftover(match: re.Match[str]) -> str:
        expected_token = f"ZZPROTECTEDZZ{match.group(1)}ZZ"
        return protected.get(expected_token, _UNRECOVERABLE_PLACEHOLDER)

    return _LEFTOVER_PROTECTED_TOKEN_RE.sub(_resolve_leftover, translated)


_en_pt_br_model: _OpusModel | None = None
_pt_en_model: _OpusModel | None = None


def _get_en_pt_br_model(model_dir: Path) -> _OpusModel:
    global _en_pt_br_model
    if _en_pt_br_model is None:
        _en_pt_br_model = _OpusModel(model_dir, target_tag=">>pob<<")
    return _en_pt_br_model


def _get_pt_en_model(model_dir: Path) -> _OpusModel:
    global _pt_en_model
    if _pt_en_model is None:
        _pt_en_model = _OpusModel(model_dir, target_tag=None)
    return _pt_en_model


async def translate_en_to_pt_br(text: str, model_dir: Path, glossary_terms: tuple[str, ...] = ()) -> str:
    model = _get_en_pt_br_model(model_dir)
    return await asyncio.to_thread(_protect_and_translate, model, text, glossary_terms)


async def translate_pt_to_en(text: str, model_dir: Path) -> str:
    model = _get_pt_en_model(model_dir)
    return await asyncio.to_thread(_protect_and_translate, model, text, ())
