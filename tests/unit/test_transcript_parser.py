from meeting_copilot.audio.transcript_parser import (
    is_noise_line,
    normalize_text,
    parse_line,
    strip_control_sequences,
)


def test_strip_ansi_and_carriage_return():
    raw = "\x1b[2K\rWe should define a common retry policy."
    assert strip_control_sequences(raw) == "We should define a common retry policy."


def test_parse_line_removes_timestamp_prefix():
    raw = "[00:00:12.340 --> 00:00:14.920]   We need retries.\n"
    assert parse_line(raw) == "We need retries."


def test_parse_line_drops_banner_lines():
    assert parse_line("whisper_init_from_file: loading model\n") is None
    assert parse_line("[Start speaking]\n") is None
    assert parse_line("   \n") is None
    assert parse_line("(BLANK_AUDIO)\n") is None


def test_parse_line_keeps_real_speech():
    assert parse_line("Do you agree with this approach?\n") == "Do you agree with this approach?"


def test_parse_line_drops_whisper_non_speech_placeholders():
    # whisper.cpp's known hallucination on unclear/foreign-language audio:
    # a bracketed English annotation instead of real words. Reported
    # 2026-07-23 (showed up translated as "(falando língua estrangeira)"
    # in the live translation panel).
    assert parse_line("(speaking in foreign language)\n") is None
    assert parse_line("(Speaking in a foreign language)\n") is None
    assert parse_line("[Music]\n") is None
    assert parse_line("(applause)\n") is None


def test_parse_line_keeps_speech_with_a_partial_parenthetical():
    # Only a whole line that is nothing but one bracketed phrase is
    # dropped -- real speech that happens to include a parenthetical
    # aside must survive.
    assert (
        parse_line("The retry policy (which we agreed on last week) needs updating.\n")
        == "The retry policy (which we agreed on last week) needs updating."
    )


def test_is_noise_line_blank():
    assert is_noise_line("")
    assert not is_noise_line("hello world")


def test_normalize_text_collapses_whitespace_and_lowercases():
    assert normalize_text("  Hello   World  ") == "hello world"
