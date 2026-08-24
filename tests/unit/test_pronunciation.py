from meeting_copilot.context.pronunciation import (
    LOW_CONFIDENCE_THRESHOLD,
    _extract_low_confidence_words,
    match_quality_for,
)


def _fake_whisper_json(tokens: list[tuple[str, float]]) -> dict:
    return {
        "transcription": [
            {
                "text": "".join(t[0] for t in tokens),
                "tokens": [{"text": text, "p": p} for text, p in tokens],
            }
        ]
    }


def test_match_quality_close_for_near_identical_text():
    assert match_quality_for("circle back on this", "circle back on this") == "close"


def test_match_quality_close_ignores_punctuation_and_case():
    assert match_quality_for("Circle back, on this!", "circle back on this") == "close"


def test_match_quality_needs_work_for_partial_overlap():
    assert match_quality_for("circle around this", "circle back on this") == "needs_work"


def test_match_quality_unclear_for_empty_heard_text():
    assert match_quality_for("", "circle back on this") == "unclear"


def test_match_quality_unclear_for_completely_different_text():
    assert match_quality_for("completely unrelated words here", "circle back on this") == "unclear"


def test_extract_low_confidence_words_flags_words_below_threshold():
    tokens = [
        ("[_BEG_]", 0.99),
        (" Circle", 0.9),
        (" back", 0.3),
        (" on", 0.998),
        (" this", 0.4),
        (".", 0.5),
    ]
    heard_text, low_confidence = _extract_low_confidence_words(_fake_whisper_json(tokens))
    assert "Circle" in heard_text
    assert "back" in heard_text
    assert "back" in low_confidence
    assert "this" in low_confidence
    assert "Circle" not in low_confidence  # 0.9 is above LOW_CONFIDENCE_THRESHOLD


def test_extract_low_confidence_words_skips_special_and_punctuation_tokens():
    tokens = [("[_BEG_]", 0.1), (" hi", 0.9), (".", 0.1)]
    heard_text, low_confidence = _extract_low_confidence_words(_fake_whisper_json(tokens))
    assert heard_text.strip() == "hi"
    assert low_confidence == []


def test_low_confidence_threshold_is_a_real_probability():
    assert 0 < LOW_CONFIDENCE_THRESHOLD < 1
