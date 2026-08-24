from meeting_copilot.context.pronunciation_guide import respell_text, respell_word


def test_respell_word_returns_none_for_unknown_word():
    assert respell_word("kubernetes") is None
    assert respell_word("thisisnotarealword12345") is None


def test_respell_word_known_words_are_deterministic():
    # Same input always produces the same output -- no model, no
    # sampling, nothing that could vary between calls.
    assert respell_word("though") == respell_word("though")
    assert respell_word("though") is not None


def test_respell_word_marks_stressed_syllable_with_accent():
    # "though" is one syllable, entirely stressed -- DH OW1 -> accented "ôu".
    result = respell_word("though")
    assert "ô" in result or "ó" in result or "á" in result or "é" in result or "í" in result or "ú" in result


def test_respell_word_never_produces_a_coincidentally_real_portuguese_word():
    """Regression test for the exact failure mode that got the LLM-based
    approach reverted (docs/DECISIONS.md, 2026-07-22): "comfortable" must
    never respell to "confortável"/"kômfortável" (a real PT word that
    merely looks similar), since the CMU dictionary pronunciation has no
    "for" syllable at all."""
    result = respell_word("comfortable")
    assert result is not None
    assert "fort" not in result
    assert result != "comfortável"
    assert result != "confortável"


def test_respell_text_leaves_unknown_words_in_original_spelling():
    result = respell_text("We should discuss the Kubernetes rollout tomorrow")
    assert "Kubernetes" in result


def test_respell_text_respells_known_words_around_unknown_ones():
    result = respell_text("the Kubernetes rollout")
    assert "Kubernetes" in result
    # "the" and "rollout" are both in the CMU dictionary -- they should
    # NOT appear in their original English spelling.
    words_in_result = result.split()
    assert "the" not in words_in_result
    assert "rollout" not in words_in_result


def test_respell_text_preserves_punctuation():
    result = respell_text("Can we circle back on this after lunch?")
    assert result.endswith("?")


def test_respell_word_handles_apostrophes():
    # Contractions ("let's", "don't") are common in real meeting speech.
    result = respell_word("don't")
    # Whether or not the CMU dict has an entry for "don't" specifically,
    # this must not raise.
    assert result is None or isinstance(result, str)


def test_respell_word_is_case_insensitive():
    assert respell_word("Though") == respell_word("though")
    assert respell_word("THOUGH") == respell_word("though")
