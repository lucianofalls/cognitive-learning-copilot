"""Structured-output schema for coach responses (section 14).

`MeetingCoachResponse` is the single shape every /api/actions/* endpoint
returns. It is sent to Ollama's `format` field as a JSON Schema so the
model is constrained to emit valid JSON, and re-validated on the way back
with Pydantic before it ever reaches the UI.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ActionName = Literal[
    "explain_context",
    "suggest_answer",
    "suggest_question",
    "disagree_politely",
    "request_clarification",
    "confirm_understanding",
    "explain_english",
]


class MeetingCoachResponse(BaseModel):
    action: ActionName
    context_pt: str = Field(default="", max_length=1200)
    suggested_answer_en: str = Field(default="", max_length=500)
    simple_opening_en: str = Field(default="", max_length=250)
    suggested_question_en: str = Field(default="", max_length=350)
    grammar_note_pt: str = Field(default="", max_length=800)
    key_vocabulary: list[str] = Field(default_factory=list, max_length=3)
    evidence_from_transcript: list[str] = Field(default_factory=list, max_length=3)
    confidence: Literal["low", "medium", "high"]
    insufficient_context: bool = False


# JSON Schema handed to Ollama's `format` parameter. Kept in sync with the
# Pydantic model above by construction (model_json_schema), but exposed as
# a plain dict because Ollama expects raw JSON Schema, not a Python type.
def response_json_schema() -> dict:
    return MeetingCoachResponse.model_json_schema()


class MeetingSummaryLLMResponse(BaseModel):
    """Schema used for the incremental summary refresh call (section 18)."""

    topic: str = ""
    facts: list[str] = Field(default_factory=list)
    proposals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confirmed_decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)


def summary_json_schema() -> dict:
    return MeetingSummaryLLMResponse.model_json_schema()


class LanguageCoachExplanation(BaseModel):
    """Language Coach Phase 1 (text Q&A) -- see docs/LANGUAGE_COACH_ARCHITECTURE.md.

    Every field maps to a specific point from
    docs/LANGUAGE_COACH_PEDAGOGY.md, referenced inline below. Kept as
    short, bounded fields for the same reasons as MeetingCoachResponse:
    Cognitive Load Theory (pedagogy doc, point 8) argues for one concept
    per interaction, not a bundle of grammar points at once.
    """

    source_sentence_en: str = Field(default="", max_length=500)
    # Focus on Form (pedagogy point 3): short, contextual, never a
    # general grammar lecture.
    explanation_pt: str = Field(max_length=900)
    # The Lexical Approach / native reasoning (pedagogy point 4).
    native_reasoning_pt: str = Field(max_length=900)
    # Retrieval Practice pairs with this via the UI (pedagogy point 5) --
    # examples are for after an attempt, not instead of one.
    alternative_examples: list[str] = Field(default_factory=list, max_length=5)
    # The Lexical Approach's "chunk to memorize," optional -- not every
    # answer centers on a reusable chunk.
    idiomatic_chunk: str = Field(default="")
    # Skill Acquisition Theory (pedagogy point 10): every explanation
    # ends with a production prompt, never just a static answer.
    follow_up_question_pt: str = Field(max_length=300)


def language_coach_explanation_json_schema() -> dict:
    return LanguageCoachExplanation.model_json_schema()


class ScenarioPractice(BaseModel):
    """Language Coach Phase 1 -- hypothetical-scenario practice.

    Situated cognition / mental simulation (pedagogy doc, point 9).
    Deliberately has no "expected_answer" field -- guided discovery, not
    a fill-in-the-blank the model already knows the answer to (see
    Retrieval Practice / Desirable Difficulties, pedagogy points 5-6).
    """

    scenario_pt: str = Field(max_length=500)
    scenario_prompt_en: str = Field(max_length=300)
    target_pattern: str = Field(default="", max_length=200)


def scenario_practice_json_schema() -> dict:
    return ScenarioPractice.model_json_schema()


class PronunciationGuide(BaseModel):
    """Language Coach -- "how does this actually sound" for a piece of
    English text, requested proactively (no recording involved -- see
    PronunciationFeedback below for the recorded-attempt case).

    English spelling routinely does not predict pronunciation ("though"/
    "through"/"tough"/"cough" all differ despite near-identical spelling)
    -- this is one of the most requested Language Coach features after
    the live translation itself: a button next to live transcript/
    translation text that shows how it actually sounds, since what's
    read is often not what a learner would guess to say out loud.

    NOT populated via an LLM call -- see context/pronunciation_guide.py.
    An LLM-based version (llama3.2:3b, asked to respell text using
    Portuguese orthography) was built and tested first, then reverted
    the same day: it hallucinated real Portuguese words that merely look
    similar to the English word instead of transcribing the actual sound
    (e.g. "comfortable" -> "kômfortável", literally just "confortável"
    with a k), and abandoned the phonetic task entirely on full
    sentences, producing a loose PT-BR paraphrase instead. A CMU
    Pronouncing Dictionary lookup (deterministic, no hallucination risk)
    replaced it -- see docs/DECISIONS.md, 2026-07-22.

    `phonetic_respelling_pt` is deliberately NOT IPA -- IPA requires
    training most learners don't have (a barrier, not a bridge). Spelled
    out using Portuguese orthography conventions instead (with accented
    vowels marking the stressed syllable, reusing a convention Brazilian
    readers already know), so a Brazilian reader can sound it out the
    same way they'd read any Portuguese word, e.g. "though" -> "d-ôu".
    This is the same "lower the barrier to entry" reasoning as
    docs/LANGUAGE_COACH_PEDAGOGY.md's Affective Filter Hypothesis
    section.
    """

    source_text_en: str = Field(default="", max_length=500)
    phonetic_respelling_pt: str = Field(max_length=500)
    # No longer LLM-generated (stress is now encoded by which vowel form
    # is used in phonetic_respelling_pt itself -- see
    # context/pronunciation_guide.py). Kept as a field for a short,
    # static explanation of that accent convention, set once by the API
    # layer, not re-derived per call.
    stress_note_pt: str = Field(default="", max_length=300)


class PronunciationFeedback(BaseModel):
    """Language Coach Phase 3a -- feedback on a recorded practice attempt.

    `heard_text`/`match_quality` are computed locally by
    `context/pronunciation.py` (whisper-cli + difflib, no LLM call);
    only `specific_feedback_pt`/`encouragement_pt` come from the model,
    so the tone rules in docs/LANGUAGE_COACH_ARCHITECTURE.md section 8
    can be enforced in the prompt: never "errado", always name what to
    adjust, always end encouraging. `encouragement_pt` has no default --
    a schema-level guarantee that every response includes it, not a
    hope the prompt gets it right every time (see section 8's tone
    rules, which call this out explicitly).
    """

    heard_text: str = Field(default="", max_length=500)
    target_text: str = Field(default="", max_length=500)
    match_quality: Literal["close", "needs_work", "unclear"]
    specific_feedback_pt: str = Field(max_length=400)
    # Bumped from the architecture doc's original 200-char draft to 300
    # after reproducing a mid-word truncation with llama3.2:3b at 200 --
    # Ollama's grammar-constrained decoding hard-stops at max_length,
    # mid-word, same failure mode already documented for
    # TranslationLLMResponse (same class of bug, different field).
    encouragement_pt: str = Field(max_length=300)


def pronunciation_feedback_json_schema() -> dict:
    return PronunciationFeedback.model_json_schema()


class TranslationLLMResponse(BaseModel):
    """Schema used for the periodic PT-BR translation refresh call."""

    # No default: a translation call should never return "". max_length
    # sits at 1700 -- safely under the ~1900 threshold where this Ollama
    # build's GBNF grammar generator silently 400s ("failed to parse
    # grammar", verified empirically, works fine up to 1800), but high
    # enough to avoid the truncation bug found 2026-07-20: at 1000, a
    # translation of a long accumulated transcript chunk (PT-BR tends to
    # run ~15-20% longer than the English source) got cut off mid-word,
    # confirmed by reproducing it with a ~1100-char input.
    translated_pt: str = Field(max_length=1700)


def translation_json_schema() -> dict:
    return TranslationLLMResponse.model_json_schema()
