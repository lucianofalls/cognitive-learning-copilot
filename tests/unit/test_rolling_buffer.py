from datetime import datetime, timedelta

from meeting_copilot.context.rolling_buffer import RollingTranscriptBuffer
from meeting_copilot.models import TranscriptSegment


def _segment(text: str, created_at: datetime) -> TranscriptSegment:
    return TranscriptSegment(text=text, normalized_text=text.lower(), stable=True, created_at=created_at)


def test_evicts_segments_older_than_window():
    buffer = RollingTranscriptBuffer(window_seconds=90)
    now = datetime.now().astimezone()

    buffer.add(_segment("old segment", now - timedelta(seconds=200)), now=now)
    buffer.add(_segment("recent segment", now - timedelta(seconds=10)), now=now)

    assert buffer.recent_text(now=now) == "recent segment"
    assert len(buffer) == 1


def test_recent_text_joins_in_order():
    buffer = RollingTranscriptBuffer(window_seconds=90)
    now = datetime.now().astimezone()

    buffer.add(_segment("first.", now - timedelta(seconds=5)), now=now)
    buffer.add(_segment("second.", now - timedelta(seconds=2)), now=now)

    assert buffer.recent_text(now=now) == "first. second."


def test_clear_empties_buffer():
    buffer = RollingTranscriptBuffer(window_seconds=90)
    now = datetime.now().astimezone()
    buffer.add(_segment("hello", now), now=now)
    buffer.clear()
    assert len(buffer) == 0
    assert buffer.recent_text(now=now) == ""
