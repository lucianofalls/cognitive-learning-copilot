"""Deduplicates overlapping transcript segments from whisper-stream.

whisper-stream re-transcribes a sliding audio window, so consecutive
segments commonly overlap: the tail of segment N repeats as the head of
segment N+1. This module removes exact repeats within a short time
window and trims longest common prefix/suffix overlaps so the rolling
transcript reads naturally instead of stuttering.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from meeting_copilot.audio.transcript_parser import normalize_text

DEDUPLICATION_WINDOW_SECONDS = 15


@dataclass
class _SeenEntry:
    normalized_text: str
    seen_at: datetime


def _longest_common_overlap(previous: str, current: str, max_check: int = 200) -> int:
    """Length of the longest suffix of `previous` that is a prefix of `current`.

    Bounded by max_check characters so a very long previous segment does
    not make this O(n^2) on realistic transcript lengths.
    """
    previous = previous[-max_check:]
    current = current[:max_check]
    max_overlap = min(len(previous), len(current))
    for length in range(max_overlap, 0, -1):
        if previous[-length:] == current[:length]:
            return length
    return 0


@dataclass
class Deduplicator:
    """Stateful deduplicator: feed it lines in arrival order."""

    window_seconds: int = DEDUPLICATION_WINDOW_SECONDS
    _recent: deque[_SeenEntry] = field(default_factory=deque)
    _last_stable_text: str = ""

    def _evict_expired(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self._recent and self._recent[0].seen_at < cutoff:
            self._recent.popleft()

    def is_exact_duplicate(self, text: str, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        self._evict_expired(now)
        normalized = normalize_text(text)
        if not normalized:
            return True
        for entry in self._recent:
            if entry.normalized_text == normalized:
                return True
        self._recent.append(_SeenEntry(normalized_text=normalized, seen_at=now))
        return False

    def trim_overlap(self, text: str) -> str:
        """Remove the portion of `text` that overlaps the previous stable text."""
        if not self._last_stable_text:
            self._last_stable_text = text
            return text
        overlap = _longest_common_overlap(self._last_stable_text, text)
        trimmed = text[overlap:].lstrip()
        self._last_stable_text = text
        return trimmed if trimmed else text
