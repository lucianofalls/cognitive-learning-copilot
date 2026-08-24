"""Turns raw whisper-stream stdout lines into clean text.

whisper-stream prints control characters used to redraw the terminal line
in place (its "sliding window" UX), plus occasional bracketed timestamps
and status lines such as "[Start speaking]". None of that belongs in a
transcript. This module is intentionally conservative: if a line does not
look like transcribed speech, it is dropped rather than guessed at.
"""

from __future__ import annotations

import re

# ANSI escape sequences (colors, cursor movement) and the \r whisper-stream
# uses to redraw a line in place.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_CARRIAGE_RETURN_RE = re.compile(r"\r")

# whisper-stream prefixes committed lines with a bracketed timestamp range,
# e.g. "[00:00:12.340 --> 00:00:14.920]". Capture the text after it.
_TIMESTAMP_PREFIX_RE = re.compile(
    r"^\s*\[\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}\]\s*"
)

# Status/banner lines that whisper-stream prints and that are not speech.
_NOISE_PATTERNS = (
    re.compile(r"^\s*$"),
    re.compile(r"^\[Start speaking\]", re.IGNORECASE),
    re.compile(r"^whisper_", re.IGNORECASE),
    re.compile(r"^main:", re.IGNORECASE),
    re.compile(r"^system_info:", re.IGNORECASE),
    re.compile(r"^\s*\(\s*BLANK_AUDIO\s*\)\s*$", re.IGNORECASE),
    # whisper.cpp's known non-speech hallucination pattern: when audio is
    # unclear, silent, or in a language the loaded model doesn't expect
    # (e.g. Portuguese fed to the English-only small.en model), it
    # sometimes "transcribes" a bracketed English annotation instead of
    # real words -- "(speaking in foreign language)", "(music playing)",
    # "[Music]", "(applause)", etc. Left unfiltered, that placeholder text
    # flows through translation like real content and shows up as
    # "(falando língua estrangeira)" -- reported 2026-07-23, confusing and
    # useless. A whole line that is nothing but one bracket/parenthesis-
    # wrapped phrase is never real transcribed speech (people don't say
    # their entire sentence as a single parenthetical), so this is safe
    # to drop outright rather than trying to enumerate every phrase.
    re.compile(r"^\s*[(\[][^()\[\]]{2,80}[)\]]\s*$"),
)


def strip_control_sequences(raw_line: str) -> str:
    """Remove ANSI escapes and carriage returns from a raw stdout line."""
    without_ansi = _ANSI_RE.sub("", raw_line)
    # A bare \r means "redraw this line" -- keep only the text after the
    # last one, which is the most recent version of the line.
    if "\r" in without_ansi:
        without_ansi = without_ansi.split("\r")[-1]
    return without_ansi.strip("\n")


def is_noise_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in _NOISE_PATTERNS)


def parse_line(raw_line: str) -> str | None:
    """Extract usable transcript text from one raw whisper-stream line.

    Returns None when the line carries no usable text (banner, blank,
    control-only line).
    """
    cleaned = strip_control_sequences(raw_line)
    cleaned = _TIMESTAMP_PREFIX_RE.sub("", cleaned).strip()

    if is_noise_line(cleaned):
        return None

    return cleaned


def normalize_text(text: str) -> str:
    """Lowercase + collapse whitespace, used for comparison, not display."""
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed.lower()
