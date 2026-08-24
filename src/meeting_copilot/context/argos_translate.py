"""Local NMT-based EN->PT translation via Argos Translate (CTranslate2).

Deliberately NOT an LLM call -- see docs/DECISIONS.md, 2026-07-20. An
Ollama LLM (any size tried) is the wrong tool for continuous live
translation: general chat models carry JSON-schema/instruction-
following overhead a dedicated translator doesn't need, and the small
model tried to speed it up was unreliable (echoed its own prompt on
~50% of real-session translations). Argos Translate is the same
category of tool Google/Apple use for on-device translation -- a small
model trained only to translate, no schema, no glossary-in-prompt
instructions to (maybe) follow. Measured: ~6-10s to load once per
process, then ~0.00-0.1s per call, vs 15-25s per call for the Ollama
path this replaces.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading

from meeting_copilot.logging_config import log_event

logger = logging.getLogger(__name__)

_PAUSE_MARKER_RE = re.compile(r"\[pausa:\s*[\d.,]+\s*s\]", re.IGNORECASE)

# Safety net for _translate_sync's placeholder tokens below -- confirmed
# 2026-08-12 (in opus_mt.py, same protect/restore approach) that
# "ZZPROTECTEDZZ{n}ZZ" does NOT reliably survive NMT tokenization intact;
# a real session leaked a Z-short version straight into the translation
# shown to the user. The digit run survives far more reliably than the
# letter run around it, so this recovers the original via that digit even
# when the letters got mangled -- exact Z-count no longer required. If
# even the digit is gone, fall back to a visible placeholder instead of
# leaking the raw internal token into the UI.
_LEFTOVER_PROTECTED_TOKEN_RE = re.compile(r"Z{1,4}\s*PROTECTED\s*Z{0,4}\s*(\d+)\s*Z{0,4}", re.IGNORECASE)
_UNRECOVERABLE_PLACEHOLDER = "[não traduzido]"

_load_lock = threading.Lock()
_model_loaded = False


def _ensure_loaded() -> None:
    """Install the en->pt package on first use and warm the model. Idempotent."""
    global _model_loaded
    if _model_loaded:
        return
    with _load_lock:
        if _model_loaded:
            return
        import argostranslate.package
        import argostranslate.translate

        # argostranslate.utils sets its OWN logger to INFO at import time
        # (`logger.setLevel(logging.INFO)` in its module body), which wins
        # over any level set on it *before* this import -- see
        # logging_config.py's configure_logging(), which runs first but
        # can't win against a level argostranslate sets afterward, on its
        # own logger, when it's actually imported here. That logger's
        # INFO level logs the raw text being translated on every call
        # (live transcript content) -- must stay silenced. Re-apply after
        # import, not before.
        logging.getLogger("argostranslate.utils").setLevel(logging.WARNING)

        installed = argostranslate.package.get_installed_packages()
        if not any(p.from_code == "en" and p.to_code == "pt" for p in installed):
            log_event(logger, "argos_translate", "installing_package", pair="en->pt")
            argostranslate.package.update_package_index()
            available = argostranslate.package.get_available_packages()
            pkg = next(p for p in available if p.from_code == "en" and p.to_code == "pt")
            argostranslate.package.install_from_path(pkg.download())
        # Cheap call to force the model into memory now rather than on
        # the first real request.
        argostranslate.translate.translate("ready", "en", "pt")
        _model_loaded = True
        log_event(logger, "argos_translate", "model_ready")


def _translate_sync(text: str, glossary_terms: tuple[str, ...]) -> str:
    """Runs on a worker thread -- argostranslate is synchronous/CPU-bound."""
    import argostranslate.translate

    _ensure_loaded()

    # Pause markers and glossary terms aren't in the NMT model's
    # training data -- protect them with plain-ASCII placeholders and
    # restore them afterward instead of trusting the model to preserve or
    # translate them correctly. The exact-token replace below is the
    # common case; _LEFTOVER_PROTECTED_TOKEN_RE right after it is the
    # safety net for when the model doesn't preserve the token intact
    # (see that regex's comment above).
    protected: dict[str, str] = {}

    def protect(original: str) -> str:
        token = f"ZZPROTECTEDZZ{len(protected)}ZZ"
        protected[token] = original
        return token

    working = _PAUSE_MARKER_RE.sub(lambda m: protect(m.group(0)), text)
    for term in glossary_terms:
        if term and term in working:
            working = working.replace(term, protect(term))

    translated = argostranslate.translate.translate(working, "en", "pt")

    for token, original in protected.items():
        translated = translated.replace(token, original)

    def _resolve_leftover(match: re.Match[str]) -> str:
        expected_token = f"ZZPROTECTEDZZ{match.group(1)}ZZ"
        return protected.get(expected_token, _UNRECOVERABLE_PLACEHOLDER)

    return _LEFTOVER_PROTECTED_TOKEN_RE.sub(_resolve_leftover, translated)


async def translate_en_to_pt(text: str, glossary_terms: tuple[str, ...] = ()) -> str:
    return await asyncio.to_thread(_translate_sync, text, glossary_terms)


async def wait_ready(timeout: float = 15.0) -> bool:
    """Blocks until the app-startup warm-up has finished loading the model,
    or `timeout` elapses. Returns whether it became ready.

    Without this, a session started right after the app boots (before
    `main.py`'s background warm-up task finishes, measured ~6-10s) pays the
    cold-load cost on its first real translation instead of getting the
    ~0.00-0.1s warm path -- see docs/DECISIONS.md, 2026-07-20. Callers
    should await this before starting a session, not before every call:
    `_model_loaded` stays true for the life of the process once set.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    while not _model_loaded:
        if asyncio.get_event_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.1)
    return True
