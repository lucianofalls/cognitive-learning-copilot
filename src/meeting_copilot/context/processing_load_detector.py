"""Detects which of Gile's four interpreting Effort Models is likely
straining for the user right now, from real signals already present in
transcript segments -- pure heuristics, no ML model, no network call, no
LLM call. Matches this project's own preference for simple, testable
implementations over adding a RAG/vector DB/autonomous agent for
something a few heuristics already handle well.

Implements the research behind Gile's Effort Models, Baddeley's
phonological loop, and Horwitz/Eysenck on anxiety and attention as they
apply to real-time bilingual production under working-memory load.

Wired into both coach systems (`services/coach_service.py`,
`services/language_coach_service.py`). This module itself stays
standalone and fully unit-testable on its own: no FastAPI/session
dependency, callers pass in whatever segments they want analyzed.
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field

from meeting_copilot.models import TranscriptSegment

# Effort a signal maps to, per this project's mapping of five named
# real-time processing difficulties onto Gile's four efforts.
Effort = Literal["listening_analysis", "memory", "production", "coordination"]

# How long a gap between two consecutive segments has to be before it
# counts as evidence of Memory Effort strain (holding the sentence start
# while still processing/formulating the rest -- theory #15b). This is a
# starting default, not a validated clinical threshold; tune against real
# usage rather than treating it as precise.
DEFAULT_MEMORY_GAP_SECONDS = 3.5

# Self-correction / restart markers (Production/Coordination Effort,
# theory #15a) -- a word immediately repeated, or an explicit restart
# phrase in either language this app's two pipelines produce.
_IMMEDIATE_REPEAT_RE = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)
_RESTART_MARKERS = (
    "i mean",
    "sorry, i",
    "no wait",
    "let me rephrase",
    "quer dizer",
    "desculpa, eu",
    "melhor dizendo",
    "deixa eu recome",  # matches "recomeçar"/"recomecar" ASR variants
)

# Explicit repeat/slow-down requests (Listening & Analysis Effort,
# theory #15a) -- the user (or their conversation partner, depending on
# which pipeline's segments are passed in) asking to hear something again.
_REPEAT_REQUEST_MARKERS = (
    "can you repeat",
    "say that again",
    "what did you say",
    "could you slow down",
    "pode repetir",
    "não entendi",
    "nao entendi",
    "de novo, por favor",
    "como assim",
)


class ProcessingLoadSignal(BaseModel):
    """One window's worth of analysis. `dominant_effort` is `None` when
    there isn't enough evidence to point at one specific effort -- callers
    should treat that as "don't adapt anything yet", not as a default
    guess."""

    dominant_effort: Effort | None
    counts: dict[Effort, int] = Field(default_factory=dict)
    segments_analyzed: int
    confidence: Literal["low", "medium", "high"]


class ProcessingLoadDetector:
    """Pure logic, no I/O, no framework dependency -- same shape as
    `context/spaced_repetition.py` and `context/rolling_buffer.py`.
    Construct once, call `analyze()` with whatever window of segments the
    caller wants examined (e.g. `RollingTranscriptBuffer.recent_segments()`
    from either the forward or reverse pipeline -- this class doesn't care
    which, the caller decides what's being analyzed for what purpose)."""

    def __init__(self, memory_gap_seconds: float = DEFAULT_MEMORY_GAP_SECONDS) -> None:
        self.memory_gap_seconds = memory_gap_seconds

    def analyze(self, segments: list[TranscriptSegment]) -> ProcessingLoadSignal:
        counts: dict[Effort, int] = {
            "listening_analysis": 0,
            "memory": 0,
            "production": 0,
            "coordination": 0,
        }

        counts["memory"] = self._count_memory_gaps(segments)

        for segment in segments:
            text = segment.text.lower()
            counts["production"] += self._count_self_corrections(text)
            counts["listening_analysis"] += self._count_repeat_requests(text)

        # Coordination strain (juggling "what was just heard" against
        # "what to say next") isn't independently observable from text
        # alone with this simple a heuristic -- treat overlapping
        # production + memory signals in the same window as a weak proxy
        # rather than inventing a fabricated independent signal for it.
        if counts["production"] > 0 and counts["memory"] > 0:
            counts["coordination"] = min(counts["production"], counts["memory"])

        dominant = self._pick_dominant(counts)
        confidence = self._confidence(len(segments))

        return ProcessingLoadSignal(
            dominant_effort=dominant,
            counts=counts,
            segments_analyzed=len(segments),
            confidence=confidence,
        )

    def _count_memory_gaps(self, segments: list[TranscriptSegment]) -> int:
        if len(segments) < 2:
            return 0
        threshold = timedelta(seconds=self.memory_gap_seconds)
        gaps = 0
        for previous, current in zip(segments, segments[1:]):
            if current.created_at - previous.created_at >= threshold:
                gaps += 1
        return gaps

    def _count_self_corrections(self, text: str) -> int:
        count = len(_IMMEDIATE_REPEAT_RE.findall(text))
        count += sum(1 for marker in _RESTART_MARKERS if marker in text)
        return count

    def _count_repeat_requests(self, text: str) -> int:
        return sum(1 for marker in _REPEAT_REQUEST_MARKERS if marker in text)

    def _pick_dominant(self, counts: dict[Effort, int]) -> Effort | None:
        # Require at least two hits before naming a dominant effort --
        # one stray match (e.g. a legitimately repeated word that wasn't
        # a self-correction) shouldn't be enough to relabel the user's
        # whole state. Ties are left unresolved (None) rather than
        # picking arbitrarily.
        effort, top_count = max(counts.items(), key=lambda item: item[1])
        if top_count < 2:
            return None
        tied = [name for name, value in counts.items() if value == top_count]
        if len(tied) > 1:
            return None
        return effort

    def _confidence(self, segment_count: int) -> Literal["low", "medium", "high"]:
        if segment_count < 5:
            return "low"
        if segment_count < 15:
            return "medium"
        return "high"


# English text for both callers' LLM prompts (context_builder.py/
# language_coach_service.py already format every other context section in
# English -- only the schema fields the LLM writes back are PT-BR), and for
# the frontend badge's underlying label before pt-BR translation there.
# Wording follows theory #15's "which effort is straining" framing, not a
# generic "user is struggling" flag -- so any downstream consumer (LLM or
# UI) can tell *what kind* of help would actually help right now.
_EFFORT_LABELS: dict[Effort, str] = {
    "listening_analysis": "Listening & Analysis (trouble keeping up with incoming speech)",
    "memory": "Memory (trouble holding the start of a sentence while the rest arrives)",
    "production": "Production (trouble formulating a response in real time)",
    "coordination": "Coordination (trouble deciding what to say while still processing what was heard)",
}


def describe_for_prompt(signal: ProcessingLoadSignal) -> str:
    """Human-readable note for an LLM prompt's context section. Returns ""
    when there isn't enough evidence to name a dominant effort -- callers
    should omit the section entirely in that case rather than include a
    hedge like "no signal detected", which just adds prompt noise."""
    if signal.dominant_effort is None:
        return ""
    return (
        f"Heuristic signal (not deterministic -- calibrate against real use, "
        f"never state this as certain fact to the user): right now, Gile's "
        f"{_EFFORT_LABELS[signal.dominant_effort]} Effort appears to be the "
        f"most strained one for this specific user (confidence: "
        f"{signal.confidence}, based on {signal.segments_analyzed} recent "
        f"segments). Prefer help that relieves that specific effort (e.g. "
        f"ready-made chunks for production/coordination strain, a short gist "
        f"instead of asking for verbatim recall for memory strain, slower/"
        f"simpler phrasing for listening & analysis strain) over generic "
        f"grammar explanation."
    )
