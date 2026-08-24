"""Runs one coach action end-to-end: build prompt -> call LLM -> validate.

This is the only place that turns a SessionService's current state (rolling
transcript + summary) plus static config (profile, glossary, meeting) into
a MeetingCoachResponse. It depends on OllamaSettings and the context
builder but not on FastAPI, so it can be unit-tested with a fake LLM call.
"""

from __future__ import annotations

from typing import Any

from meeting_copilot.config import OllamaSettings
from meeting_copilot.context.context_builder import build_messages
from meeting_copilot.context.processing_load_detector import (
    ProcessingLoadDetector,
    ProcessingLoadSignal,
    describe_for_prompt,
)
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError, call_and_validate
from meeting_copilot.llm.prompt_loader import get_action_prompt, get_system_prompt
from meeting_copilot.llm.schemas import ActionName, MeetingCoachResponse
from meeting_copilot.services.session_service import SessionService


class CoachService:
    def __init__(self, ollama_settings: OllamaSettings) -> None:
        self._ollama_settings = ollama_settings
        # Pure heuristic, no settings/state of its own -- see
        # context/processing_load_detector.py. Instantiated once here the
        # same way SessionService instantiates its own local helper classes
        # directly (RollingTranscriptBuffer, SummaryManager, ...).
        self._processing_load_detector = ProcessingLoadDetector()

    async def run_action(
        self,
        action: ActionName,
        session: SessionService,
        profile: dict[str, Any],
        glossary: dict[str, Any],
        user_idea_pt: str = "",
    ) -> tuple[MeetingCoachResponse, ProcessingLoadSignal]:
        processing_load_signal = self._processing_load_detector.analyze(
            session.recent_segments_for_processing_load()
        )
        messages = build_messages(
            system_prompt=get_system_prompt(),
            action_instructions=get_action_prompt(action),
            action=action,
            profile=profile,
            meeting=session.meeting_config.model_dump(),
            glossary=glossary,
            summary_text=session.summary_manager.as_bounded_text(),
            recent_transcript=session.rolling_buffer.recent_text(),
            user_idea_pt=user_idea_pt,
            processing_load_note=describe_for_prompt(processing_load_signal),
        )

        try:
            result = await call_and_validate(messages, MeetingCoachResponse, self._ollama_settings)
        except (OllamaUnavailableError, OllamaInvalidResponseError):
            raise

        assert isinstance(result, MeetingCoachResponse)
        # Returned alongside the LLM response, never folded into
        # MeetingCoachResponse itself -- that schema is sent to Ollama's
        # JSON-Schema-constrained `format` (llm/ollama_client.py), and this
        # signal is never something the model should be asked to produce or
        # guess at (see processing_load_detector.py's module docstring: pure
        # heuristic, no LLM involved). api/actions.py merges it into the
        # HTTP response dict separately.
        return result, processing_load_signal
