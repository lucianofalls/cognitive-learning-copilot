from datetime import datetime, timedelta

from meeting_copilot.audio.deduplicator import Deduplicator, _longest_common_overlap


def test_longest_common_overlap_basic():
    assert _longest_common_overlap("we need retries", "retries and auth") == len("retries")


def test_longest_common_overlap_no_overlap():
    assert _longest_common_overlap("hello", "world") == 0


def test_exact_duplicate_within_window_is_dropped():
    dedup = Deduplicator(window_seconds=15)
    now = datetime.now().astimezone()
    assert dedup.is_exact_duplicate("We need retries.", now) is False
    assert dedup.is_exact_duplicate("We need retries.", now + timedelta(seconds=2)) is True


def test_exact_duplicate_outside_window_is_allowed_again():
    dedup = Deduplicator(window_seconds=15)
    now = datetime.now().astimezone()
    assert dedup.is_exact_duplicate("We need retries.", now) is False
    assert dedup.is_exact_duplicate("We need retries.", now + timedelta(seconds=20)) is False


def test_trim_overlap_removes_repeated_suffix_prefix():
    dedup = Deduplicator()
    first = dedup.trim_overlap("We should define a common retry policy")
    assert first == "We should define a common retry policy"
    second = dedup.trim_overlap("retry policy for every downstream consumer")
    assert second == "for every downstream consumer"


def test_trim_overlap_first_call_returns_full_text():
    dedup = Deduplicator()
    assert dedup.trim_overlap("hello world") == "hello world"
