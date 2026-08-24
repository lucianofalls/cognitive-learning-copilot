"""One-shot pronunciation check via `whisper-cli` -- Language Coach Phase 3a.

Phase 3a of docs/LANGUAGE_COACH_ARCHITECTURE.md, section 4: the cheapest
of the three pronunciation-feedback tiers documented there, built first
per "do not build the heaviest option first." No new dependency, no new
model: `whisper-cli` (confirmed present via `--help` at
`<repository_path>/build/bin/whisper-cli`, alongside but distinct from
the continuous `whisper-stream` binary the live meeting uses) already
computes per-token probabilities as part of normal decoding when asked
for `-ojf` (JSON, full detail) -- verified directly by running it on a
synthesized clip and inspecting the output's `"p"` fields, not assumed
from documentation.

Non-blocking: `asyncio.create_subprocess_exec`, matching this codebase's
CPU-bound-work pattern elsewhere (argos_translate.py, context/tts.py).
This project's "never persist audio" rule applies here exactly as it
does to tts.py's synthesized speech: the practice attempt is written to a temp
WAV only because whisper-cli needs a real file, read back out as
whatever this module returns, and the temp input/output files are
deleted in a `finally` block -- nothing survives the call.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from meeting_copilot.config import WhisperSettings

# Below this per-token probability, whisper-cli's own decoding was
# uncertain about that word -- worth surfacing as "this part was
# unclear" rather than trusting the transcription as ground truth.
# Distinct from whisper-cli's own `--word-thold` (0.01), which controls
# whether a word is *included* in the transcript at all, not whether
# it's flagged here as low-confidence.
LOW_CONFIDENCE_THRESHOLD = 0.6


class PronunciationCheckError(Exception):
    pass


class PronunciationTranscription(BaseModel):
    heard_text: str
    low_confidence_words: list[str] = []


def _normalize_words(text: str) -> list[str]:
    return [w.strip(".,!?;:\"'").lower() for w in text.split() if w.strip(".,!?;:\"'")]


def match_quality_for(heard_text: str, target_text: str) -> Literal["close", "needs_work", "unclear"]:
    """Word-level similarity via stdlib difflib -- no new dependency.

    Thresholds are deliberately coarse (three buckets, not a raw score)
    -- the tone rules in docs/LANGUAGE_COACH_ARCHITECTURE.md section 8
    care about the framing this drives (never "wrong"), not about a
    precise number the user never sees.
    """
    heard_words = _normalize_words(heard_text)
    if not heard_words:
        return "unclear"
    ratio = SequenceMatcher(None, heard_words, _normalize_words(target_text)).ratio()
    if ratio >= 0.85:
        return "close"
    if ratio >= 0.5:
        return "needs_work"
    return "unclear"


def _extract_low_confidence_words(transcription_json: dict) -> tuple[str, list[str]]:
    heard_words: list[str] = []
    low_confidence: list[str] = []
    for segment in transcription_json.get("transcription", []):
        for token in segment.get("tokens", []):
            text = token.get("text", "").strip()
            # Special tokens ("[_BEG_]", "[_TT_123]", ...) and pure
            # punctuation aren't words -- skip them for both the heard
            # text and the confidence check.
            if not text or (text.startswith("[") and text.endswith("]")):
                continue
            if not any(char.isalnum() for char in text):
                continue
            heard_words.append(text)
            if token.get("p", 1.0) < LOW_CONFIDENCE_THRESHOLD:
                low_confidence.append(text)
    return " ".join(heard_words), low_confidence


async def transcribe_attempt(audio_bytes: bytes, whisper_settings: WhisperSettings) -> PronunciationTranscription:
    """Run whisper-cli once over a short practice recording (WAV bytes)."""
    whisper_cli = whisper_settings.cli_binary_path_expanded
    if not whisper_cli.exists():
        raise PronunciationCheckError(f"whisper-cli not found at {whisper_cli}.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
        tmp_in.write(audio_bytes)
        input_path = Path(tmp_in.name)
    output_prefix = input_path.with_suffix("")  # whisper-cli appends its own extension
    output_json_path = output_prefix.with_suffix(".json")

    try:
        process = await asyncio.create_subprocess_exec(
            str(whisper_cli),
            "-m",
            str(whisper_settings.model_path_expanded),
            "-f",
            str(input_path),
            "-ojf",
            "-of",
            str(output_prefix),
            "-np",
            "-l",
            whisper_settings.language,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip() or "whisper-cli exited with a non-zero status."
            raise PronunciationCheckError(detail)
        if not output_json_path.exists():
            raise PronunciationCheckError("whisper-cli did not produce a JSON output file.")
        transcription_json = json.loads(output_json_path.read_text(encoding="utf-8"))
        heard_text, low_confidence_words = _extract_low_confidence_words(transcription_json)
        return PronunciationTranscription(heard_text=heard_text, low_confidence_words=low_confidence_words)
    finally:
        input_path.unlink(missing_ok=True)
        output_json_path.unlink(missing_ok=True)
