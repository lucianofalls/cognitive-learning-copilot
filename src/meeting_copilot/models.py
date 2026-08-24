"""Shared Pydantic models used across the audio, context, and API layers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class TranscriptSegment(BaseModel):
    id: str = Field(default_factory=_new_id)
    created_at: datetime = Field(default_factory=_now)
    text: str
    normalized_text: str
    stable: bool = False
    source: str = "whisper-stream"


class MeetingConfig(BaseModel):
    title: str = ""
    objective: str = ""
    agenda: list[str] = Field(default_factory=list)
    expected_topics: list[str] = Field(default_factory=list)
    known_systems: list[str] = Field(default_factory=list)
    known_acronyms: list[str] = Field(default_factory=list)
    desired_outcome: str = ""
    response_tone: str = "professional-simple"
    english_variant: str = "en-US"
    context_output_language: str = "pt-BR"
    expected_speakers: list[str] = Field(default_factory=list)
    notes: str = ""


class MeetingSummary(BaseModel):
    topic: str = ""
    facts: list[str] = Field(default_factory=list)
    proposals: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confirmed_decisions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)


class ApprovedMemoryItem(BaseModel):
    id: str = Field(default_factory=_new_id)
    text: str
    approved_at: datetime = Field(default_factory=_now)


class FeedbackEntry(BaseModel):
    action: str
    rating: Literal[
        "useful",
        "too_long",
        "difficult_to_pronounce",
        "out_of_context",
        "incorrect",
    ]
    sentence_length: int = 0
    timestamp: datetime = Field(default_factory=_now)


class SessionStatus(BaseModel):
    microphone: Literal["unknown", "ready", "error"] = "unknown"
    whisper: Literal["stopped", "starting", "running", "error"] = "stopped"
    ollama: Literal["unknown", "ready", "unavailable"] = "unknown"
    session_id: str | None = None
    started_at: datetime | None = None
    # Whether this session is writing the PT-BR translation + summary to a
    # local markdown file (privacy.persist_learning_notes). Surfaced to the
    # UI so persistence is never silent -- see docs/PRIVACY.md.
    learning_persisted: bool = False
    # Status of the second, independent continuous whisper-stream process
    # that listens for Portuguese speech (reverse translation, "Falar em
    # português" live pipeline) -- deliberately a separate field from
    # `whisper` above, never conflated with it: this project's rule that
    # whisper.cpp and Ollama failures must be handled independently
    # applies here too, so this stream failing must never be reported as
    # the main English pipeline failing.
    # "disabled" means whisper.enable_portuguese_stream is false or the
    # multilingual model file is missing -- distinct from "stopped" (the
    # whole session ended) and "error" (crashed). "paused" is distinct
    # from both: the session is still running, but the user minimized
    # the "FALAR EM PORTUGUÊS" panel (web/app.js), which stops this one
    # process specifically to save CPU -- see SessionService.
    # pause_portuguese_stream/resume_portuguese_stream.
    whisper_pt: Literal["disabled", "stopped", "starting", "running", "paused", "error"] = "disabled"
