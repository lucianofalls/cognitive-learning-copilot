from datetime import datetime, timedelta

from meeting_copilot.context.processing_load_detector import (
    DEFAULT_MEMORY_GAP_SECONDS,
    ProcessingLoadDetector,
    ProcessingLoadSignal,
    describe_for_prompt,
)
from meeting_copilot.models import TranscriptSegment


def _segment(text: str, created_at: datetime) -> TranscriptSegment:
    return TranscriptSegment(text=text, normalized_text=text.lower(), stable=True, created_at=created_at)


def test_no_signal_returns_none_dominant_effort():
    detector = ProcessingLoadDetector()
    now = datetime.now().astimezone()
    segments = [
        _segment("we should ship this next week.", now),
        _segment("sounds good to me.", now + timedelta(seconds=1)),
    ]

    result = detector.analyze(segments)

    assert result.dominant_effort is None
    assert result.segments_analyzed == 2


def test_repeated_long_pauses_signal_memory_effort():
    detector = ProcessingLoadDetector(memory_gap_seconds=3.0)
    now = datetime.now().astimezone()
    segments = [
        _segment("so about the deadline", now),
        _segment("i think we can move it", now + timedelta(seconds=5)),
        _segment("to next friday", now + timedelta(seconds=11)),
    ]

    result = detector.analyze(segments)

    assert result.counts["memory"] == 2
    assert result.dominant_effort == "memory"


def test_self_correction_markers_signal_production_effort():
    detector = ProcessingLoadDetector()
    now = datetime.now().astimezone()
    segments = [
        _segment("we should, i mean, we could try that", now),
        _segment("sorry, i meant the the other approach", now + timedelta(seconds=1)),
    ]

    result = detector.analyze(segments)

    assert result.counts["production"] >= 2
    assert result.dominant_effort == "production"


def test_repeat_request_markers_signal_listening_analysis_effort():
    detector = ProcessingLoadDetector()
    now = datetime.now().astimezone()
    segments = [
        _segment("sorry, can you repeat that?", now),
        _segment("desculpa, não entendi", now + timedelta(seconds=1)),
    ]

    result = detector.analyze(segments)

    assert result.counts["listening_analysis"] == 2
    assert result.dominant_effort == "listening_analysis"


def test_single_stray_match_is_not_enough_to_name_a_dominant_effort():
    detector = ProcessingLoadDetector()
    now = datetime.now().astimezone()
    segments = [_segment("i mean, that works fine", now)]

    result = detector.analyze(segments)

    assert result.counts["production"] == 1
    assert result.dominant_effort is None


def test_tied_signals_are_left_unresolved():
    detector = ProcessingLoadDetector()
    now = datetime.now().astimezone()
    segments = [
        _segment("can you repeat that?", now),
        _segment("i mean, that could work", now + timedelta(seconds=1)),
        _segment("sorry, can you repeat this?", now + timedelta(seconds=2)),
        _segment("no wait, that's not right", now + timedelta(seconds=3)),
    ]

    result = detector.analyze(segments)

    assert result.counts["listening_analysis"] == result.counts["production"] == 2
    assert result.dominant_effort is None


def test_confidence_scales_with_segment_count():
    detector = ProcessingLoadDetector()
    now = datetime.now().astimezone()

    few = [_segment("hi", now)]
    assert detector.analyze(few).confidence == "low"

    medium = [_segment("hi", now + timedelta(seconds=i)) for i in range(7)]
    assert detector.analyze(medium).confidence == "medium"

    many = [_segment("hi", now + timedelta(seconds=i)) for i in range(20)]
    assert detector.analyze(many).confidence == "high"


def test_default_memory_gap_threshold_is_documented_constant():
    assert DEFAULT_MEMORY_GAP_SECONDS == 3.5


def test_describe_for_prompt_returns_empty_string_when_no_dominant_effort():
    signal = ProcessingLoadSignal(dominant_effort=None, counts={}, segments_analyzed=2, confidence="low")

    assert describe_for_prompt(signal) == ""


def test_describe_for_prompt_names_the_effort_and_confidence():
    signal = ProcessingLoadSignal(
        dominant_effort="production",
        counts={"production": 3},
        segments_analyzed=5,
        confidence="medium",
    )

    note = describe_for_prompt(signal)

    assert "Production" in note
    assert "medium" in note
    assert "not deterministic" in note
