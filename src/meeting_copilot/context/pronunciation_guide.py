"""Deterministic English pronunciation respelling via the CMU Pronouncing
Dictionary -- no LLM involved, by design.

Replaces an earlier LLM-based approach (asking llama3.2:3b to guess a
Portuguese-orthography phonetic respelling) that was tested directly
and found unreliable 2026-07-22: it repeatedly hallucinated real
Portuguese words that merely *look* similar to the English word instead
of transcribing the actual sound (e.g. "comfortable" -> "kômfortável",
literally just "confortável" with a k -- wrong; the real pronunciation
has no "for" syllable at all), and it abandoned the phonetic task
entirely on full sentences, producing a loose PT-BR paraphrase instead
of a respelling. A pronunciation guide that's confidently wrong is
worse than no guide at all for a language learner -- see
docs/DECISIONS.md, 2026-07-22.

The `pronouncing` package (CMU Pronouncing Dictionary, ~135k English
words, pure Python, no network call, no model download -- confirmed via
`pip show pronouncing`) gives ARPAbet phonemes with a stress digit per
vowel -- entirely deterministic, the same word always respells the same
way, and it can never confuse a word for an unrelated real Portuguese
word. Words absent from the dictionary (proper nouns, technical jargon
like "Kubernetes" -- confirmed absent by checking directly) are left in
their original English spelling rather than guessed at: an honest gap
beats a confident wrong guess, same reasoning as above.

Stress is encoded by which vowel form is used, not a separate marker:
Portuguese readers already read acute/circumflex accents as "stress
here" in their own language, so the primary-stressed vowel gets an
accented form (`á`, `é`, `í`, `ó` ...) and unstressed vowels get the
plain form -- this reuses an orthographic convention a Portuguese
reader already knows instead of introducing a new one.
"""

from __future__ import annotations

import re

import pronouncing

# ARPAbet vowel phoneme -> (stressed spelling, unstressed spelling).
# Stressed forms use PT-BR accents so the stressed syllable is visually
# obvious the same way it would be in a Portuguese word. Approximations,
# not a claim of phonetic precision -- several English vowel contrasts
# (IH vs IY, UH vs UW) have no Portuguese equivalent and collapse to the
# same letter here; that's an acceptable loss for "how do I roughly say
# this," not a transcription tool for linguists.
_VOWELS: dict[str, tuple[str, str]] = {
    "AA": ("á", "a"),
    "AE": ("é", "e"),
    "AH": ("â", "a"),
    "AO": ("ó", "o"),
    "AW": ("áu", "au"),
    "AY": ("ái", "ai"),
    "EH": ("é", "e"),
    "ER": ("êr", "er"),
    "EY": ("éi", "ei"),
    "IH": ("i", "i"),
    "IY": ("í", "i"),
    "OW": ("ôu", "ou"),
    "OY": ("ói", "oi"),
    "UH": ("ú", "u"),
    "UW": ("ú", "u"),
}

# ARPAbet consonant phoneme -> Portuguese-orthography approximation.
# A few notes on choices that aren't obvious:
# - DH/TH (the two English "th" sounds, as in "this"/"think"): neither
#   exists in Portuguese at all. Approximated as "d"/"t" -- the closest
#   single-letter Portuguese sound, and the substitution Portuguese
#   speakers already make naturally when they don't produce "th".
# - SH -> "x" (as in "xícara") and ZH -> "j" (as in "já") are close,
#   natural fits -- Portuguese already spells those sounds this way.
# - HH (English "h", as in "house"): Portuguese "h" is silent, so this
#   respells as "rr" (the guttural R Brazilians already produce, e.g.
#   "carro"), the closest sound Portuguese actually has.
# - W (consonant "w", as in "way"): Portuguese has no "w" consonant;
#   respelled as "u" (the closest glide, e.g. "uau").
_CONSONANTS: dict[str, str] = {
    "B": "b",
    "CH": "tch",
    "D": "d",
    "DH": "d",
    "F": "f",
    "G": "g",
    "HH": "rr",
    "JH": "dj",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "n",
    "P": "p",
    "R": "r",
    "S": "s",
    "SH": "x",
    "T": "t",
    "TH": "t",
    "V": "v",
    "W": "u",
    "Y": "i",
    "Z": "z",
    "ZH": "j",
}

_WORD_RE = re.compile(r"[A-Za-z']+")


def _respell_phones(phones: str) -> str:
    # A hyphen only goes in front of a vowel (never between two
    # consonants) -- this groups each syllable's leading consonant(s)
    # and trailing consonant(s) with the vowel between them, e.g.
    # "schedule" (S K EH1 JH UH0 L) -> "sk-édj-ul" instead of splitting
    # every single phone apart. Not real syllabification (which would
    # also split consonant clusters like "sk" across syllable
    # boundaries when appropriate), but far more readable than
    # phone-by-phone hyphens for a quick glance.
    groups: list[str] = []
    current = ""
    for phone in phones.split():
        stress = phone[-1] if phone[-1].isdigit() else None
        base = phone[:-1] if stress is not None else phone
        if base in _VOWELS:
            if current:
                groups.append(current)
            stressed_form, unstressed_form = _VOWELS[base]
            current = stressed_form if stress == "1" else unstressed_form
        else:
            current += _CONSONANTS.get(base, base.lower())
    if current:
        groups.append(current)
    return "-".join(groups)


def respell_word(word: str) -> str | None:
    """Returns a PT-orthography respelling of `word`, or None if it's not
    in the CMU dictionary (caller should keep the original spelling)."""
    candidates = pronouncing.phones_for_word(word.lower())
    if not candidates:
        return None
    return _respell_phones(candidates[0])


def respell_text(text: str) -> str:
    """Respells every recognized word in `text`, leaving unrecognized
    words (proper nouns, technical jargon not in the CMU dictionary) in
    their original English spelling rather than guessing.
    """

    def _replace(match: re.Match[str]) -> str:
        word = match.group(0)
        respelled = respell_word(word)
        return respelled if respelled is not None else word

    return _WORD_RE.sub(_replace, text)
