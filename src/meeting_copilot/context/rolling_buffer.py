"""Keeps only the last N seconds of transcript in memory (section 17).

This is the "recent transcript" level of context. It never touches disk:
segments older than `window_seconds` are simply dropped, which is also
how the app satisfies `privacy.persist_transcript: false` by construction
for this layer -- there is nothing to opt out of persisting because it
was never written anywhere.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from meeting_copilot.models import TranscriptSegment

DEFAULT_WINDOW_SECONDS = 90


@dataclass
class RollingTranscriptBuffer:
    window_seconds: int = DEFAULT_WINDOW_SECONDS
    _segments: deque[TranscriptSegment] = field(default_factory=deque)

    def add(self, segment: TranscriptSegment, now: datetime | None = None) -> None:
        self._segments.append(segment)
        self._evict_expired(now or datetime.now().astimezone())

    def _evict_expired(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self.window_seconds)
        while self._segments and self._segments[0].created_at < cutoff:
            self._segments.popleft()

    def recent_text(self, now: datetime | None = None) -> str:
        self._evict_expired(now or datetime.now().astimezone())
        return " ".join(segment.text for segment in self._segments if segment.text)

    def recent_segments(self, now: datetime | None = None) -> list[TranscriptSegment]:
        self._evict_expired(now or datetime.now().astimezone())
        return list(self._segments)

    def clear(self) -> None:
        self._segments.clear()

    def __len__(self) -> int:
        return len(self._segments)
