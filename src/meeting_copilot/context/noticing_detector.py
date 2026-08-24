"""Detects idioms/phrasal verbs worth actively flagging in the live
English transcript -- the proactive half of the Noticing Hypothesis
(Schmidt, 1990; docs/LANGUAGE_COACH_PEDAGOGY.md theory #2): "the coach
shouldn't wait to be asked -- it should actively flag noticeable
moments in the real, live transcript (an unusual verb tense, a phrasal
verb, an idiom) as optional, dismissible prompts, turning passive
listening into active noticing."

Deterministic curated-list lookup, not an LLM call -- same reasoning as
context/processing_load_detector.py and web/visual_anchors.js: this
runs on every new transcript segment, so it must add ~zero latency
(the ask's point 7: "must run in parallel, with zero impact on the
current transcription/translation speed"). No LLM, no schema, no
network call.
"""

from __future__ import annotations

# Curated business-meeting idioms/phrasal verbs worth actively noticing --
# deliberately small and hand-picked (ADHD_NEUROSCIENCE_REFERENCE.md rule
# #1: variation must be genuinely relevant, not noise), matching
# web/visual_anchors.js's curation approach and scale. Extend by hand as
# real sessions surface gaps, don't auto-generate from an external list.
NOTICEABLE_PATTERNS: tuple[str, ...] = (
    "circle back",
    "touch base",
    "loop in",
    "loop you in",
    "get the ball rolling",
    "on the same page",
    "low-hanging fruit",
    "table this",
    "table that",
    "push back",
    "follow up",
    "follow through",
    "take this offline",
    "at the end of the day",
    "let's unpack",
    "double down",
    "moving the needle",
    "level set",
    "deep dive",
    "boil the ocean",
    "quick win",
    "north star",
    "in the weeds",
    "put a pin in",
    "close the loop",
    "raise a flag",
    "not a hill i'd die on",
    "give and take",
    "read between the lines",
    "ballpark figure",
    "run it by",
    "keep me posted",
    "keep in the loop",
    "hash it out",
)


def find_noticeable_phrase(text: str) -> str | None:
    """Returns the first matching phrase in `text`, or None.

    Case-insensitive substring match -- same simplicity as
    SessionService._matched_phrase, no tokenization/stemming. A false
    negative here just means the coach stays silent for that segment;
    the "?" affordance on every transcript line is still there
    regardless, so nothing is ever unreachable, only unflagged.
    """
    lowered = text.lower()
    for phrase in NOTICEABLE_PATTERNS:
        if phrase in lowered:
            return phrase
    return None
