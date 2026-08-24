import pytest

from meeting_copilot.context.language_detect import detect_language


@pytest.mark.parametrize(
    "text,expected",
    [
        ("quero dizer que concordamos, mas falta definir o retry", "pt"),
        ("I want to say we agree, but we still need to define the retry", "en"),
        ("podemos adiar a reunião?", "pt"),
        ("can we push the deadline?", "en"),
        ("obrigado pela ajuda", "pt"),
        ("thanks for the help", "en"),
        ("vamos comecar", "pt"),
        ("let's start", "en"),
        ("sim", "pt"),
        ("yes", "en"),
        ("acho que sim, mas nao tenho certeza", "pt"),
        ("I think so but I'm not sure", "en"),
        ("we need to push the deadline to next week", "en"),
        ("precisamos empurrar o prazo pra semana que vem", "pt"),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_detect_language_defaults_to_pt_on_empty_or_ambiguous_text():
    assert detect_language("") == "pt"
    assert detect_language("ok") == "pt"
    assert detect_language("123") == "pt"


def test_detect_language_is_case_insensitive():
    assert detect_language("OBRIGADO PELA AJUDA") == "pt"
    assert detect_language("THANKS FOR THE HELP") == "en"


def test_pt_diacritics_alone_are_a_strong_signal():
    # A single word with a PT-only diacritic should outweigh any
    # coincidental stopword overlap.
    assert detect_language("reunião") == "pt"
