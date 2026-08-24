from meeting_copilot.context.noticing_detector import NOTICEABLE_PATTERNS, find_noticeable_phrase


def test_finds_a_known_idiom_case_insensitively():
    assert find_noticeable_phrase("Let's Circle Back on this next week.") == "circle back"


def test_returns_none_when_nothing_matches():
    assert find_noticeable_phrase("The deploy finished successfully.") is None


def test_returns_first_match_when_multiple_present():
    result = find_noticeable_phrase("Let's touch base and circle back tomorrow.")
    assert result in ("touch base", "circle back")


def test_every_pattern_is_lowercase_for_consistent_matching():
    assert all(pattern == pattern.lower() for pattern in NOTICEABLE_PATTERNS)
