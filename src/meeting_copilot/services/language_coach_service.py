"""Language Coach: on-demand grammar/idiom Q&A, scenario practice, and
pronunciation feedback.

Phase 1+3a of docs/LANGUAGE_COACH_ARCHITECTURE.md -- Phase 1 is text
only; Phase 3a adds pronunciation feedback, but the LLM call in
`pronunciation_feedback` still only ever sees text (whisper-cli's
transcription + confidence signal, computed in context/pronunciation.py
before this class is ever called) -- no audio touches this module or
Ollama. Mirrors CoachService's shape exactly (build prompt -> call LLM
-> validate), and depends on OllamaSettings but not FastAPI, so it's
unit-testable with a fake LLM call the same way. This is a deliberate
second service rather than a new ActionName on CoachService: it's a
different intent (learn *from* the meeting vs. get help *in* the
meeting) -- see docs/ARCHITECTURE.md's "Two independent refresh
strategies" precedent for why this codebase keeps differently-shaped
work in separate modules rather than one growing one.

Reuses `ollama.model` (the same model the 7 meeting-coach actions use)
rather than a dedicated model -- see docs/LANGUAGE_COACH_ARCHITECTURE.md
open question #2. A dedicated small model was tried once already for
translation (llama3.2:1b) and reverted for reliability reasons (see
docs/DECISIONS.md, 2026-07-20); no reason to assume a second one would
fare better here without evidence.
"""

from __future__ import annotations

from typing import Any, Literal

from meeting_copilot.config import OllamaSettings
from meeting_copilot.context.processing_load_detector import (
    ProcessingLoadDetector,
    ProcessingLoadSignal,
    describe_for_prompt,
)
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError, call_and_validate
from meeting_copilot.llm.prompt_loader import (
    get_language_coach_explain_prompt,
    get_language_coach_pronunciation_prompt,
    get_language_coach_scenario_prompt,
    get_language_coach_system_prompt,
)
from meeting_copilot.llm.schemas import LanguageCoachExplanation, PronunciationFeedback, ScenarioPractice
from meeting_copilot.services.session_service import SessionService

# Note: the phonetic "pronunciation guide" (how does this text actually
# sound) is deliberately NOT here -- it's context/pronunciation_guide.py,
# a pure CMU-dictionary lookup with no Ollama call at all. An LLM-based
# version was tried and reverted 2026-07-22 for reliability (see
# docs/DECISIONS.md): it hallucinated real Portuguese words that merely
# looked similar instead of transcribing the actual sound. Called
# directly from api/language_coach.py, same as context/tts.py.


def _format_learner_profile(profile: dict[str, Any]) -> str:
    user = profile.get("user", {})
    return (
        f"Native language: {user.get('native_language', 'pt-BR')}\n"
        f"English level: {user.get('english_level', 'intermediate')}"
    )


class LanguageCoachService:
    def __init__(self, ollama_settings: OllamaSettings) -> None:
        self._ollama_settings = ollama_settings
        # Same instance shape as CoachService's -- see that class's
        # __init__ comment for why this is constructed directly rather
        # than injected.
        self._processing_load_detector = ProcessingLoadDetector()

    async def explain(
        self,
        profile: dict[str, Any],
        session: SessionService,
        question: str = "",
        source_sentence_en: str = "",
    ) -> tuple[LanguageCoachExplanation, ProcessingLoadSignal]:
        """Answer a free-form question, optionally anchored to a real sentence.

        At least one of `question`/`source_sentence_en` should be
        non-empty -- the API layer enforces this before calling in.
        """
        processing_load_signal = self._processing_load_detector.analyze(
            session.recent_segments_for_processing_load()
        )
        user_sections = [f"## Learner profile\n{_format_learner_profile(profile)}"]
        if source_sentence_en:
            user_sections.append(f"## Real sentence just heard in the meeting\n{source_sentence_en}")
        if question:
            user_sections.append(f"## User's question\n{question}")
        else:
            user_sections.append(
                "## User's question\n"
                "(none -- explain what's noteworthy about this sentence for an "
                "intermediate PT-BR speaker learning English)"
            )
        processing_load_note = describe_for_prompt(processing_load_signal)
        if processing_load_note:
            user_sections.append(f"## Detected real-time processing load (theory #15)\n{processing_load_note}")

        messages = [
            {"role": "system", "content": get_language_coach_system_prompt()},
            {"role": "user", "content": f"{get_language_coach_explain_prompt()}\n\n" + "\n\n".join(user_sections)},
        ]

        try:
            result = await call_and_validate(messages, LanguageCoachExplanation, self._ollama_settings)
        except (OllamaUnavailableError, OllamaInvalidResponseError):
            raise
        assert isinstance(result, LanguageCoachExplanation)
        if not result.source_sentence_en and source_sentence_en:
            result.source_sentence_en = source_sentence_en
        return result, processing_load_signal

    async def scenario(
        self, profile: dict[str, Any], session: SessionService, target_pattern: str
    ) -> tuple[ScenarioPractice, ProcessingLoadSignal]:
        processing_load_signal = self._processing_load_detector.analyze(
            session.recent_segments_for_processing_load()
        )
        user_content = (
            f"{get_language_coach_scenario_prompt()}\n\n"
            f"## Learner profile\n{_format_learner_profile(profile)}\n\n"
            f"## Target pattern to build a scenario around\n{target_pattern}"
        )
        processing_load_note = describe_for_prompt(processing_load_signal)
        if processing_load_note:
            user_content += f"\n\n## Detected real-time processing load (theory #15)\n{processing_load_note}"

        messages = [
            {"role": "system", "content": get_language_coach_system_prompt()},
            {"role": "user", "content": user_content},
        ]

        try:
            result = await call_and_validate(messages, ScenarioPractice, self._ollama_settings)
        except (OllamaUnavailableError, OllamaInvalidResponseError):
            raise
        assert isinstance(result, ScenarioPractice)
        return result, processing_load_signal

    async def pronunciation_feedback(
        self,
        profile: dict[str, Any],
        session: SessionService,
        heard_text: str,
        target_text: str,
        match_quality: Literal["close", "needs_work", "unclear"],
        low_confidence_words: list[str],
    ) -> tuple[PronunciationFeedback, ProcessingLoadSignal]:
        """Turn a whisper-cli transcription + confidence signal into feedback.

        `heard_text`/`match_quality`/`low_confidence_words` are all
        already computed locally (context/pronunciation.py) before this
        is ever called -- this method's only job is phrasing the
        natural-language feedback per the tone rules, same division of
        labor as the rest of this file.
        """
        processing_load_signal = self._processing_load_detector.analyze(
            session.recent_segments_for_processing_load()
        )
        low_confidence_note = (
            f"Words the speech recognizer was unsure about: {', '.join(low_confidence_words)}"
            if low_confidence_words
            else "No specific words flagged as unclear by the speech recognizer."
        )
        user_content = (
            f"{get_language_coach_pronunciation_prompt()}\n\n"
            f"## Learner profile\n{_format_learner_profile(profile)}\n\n"
            f"## Target phrase\n{target_text}\n\n"
            f"## What speech-to-text heard\n{heard_text or '(nothing recognizable)'}\n\n"
            f"## Match quality (already computed, do not recompute)\n{match_quality}\n\n"
            f"## {low_confidence_note}"
        )
        processing_load_note = describe_for_prompt(processing_load_signal)
        if processing_load_note:
            user_content += f"\n\n## Detected real-time processing load (theory #15)\n{processing_load_note}"

        messages = [
            {"role": "system", "content": get_language_coach_system_prompt()},
            {"role": "user", "content": user_content},
        ]

        try:
            result = await call_and_validate(messages, PronunciationFeedback, self._ollama_settings)
        except (OllamaUnavailableError, OllamaInvalidResponseError):
            raise
        assert isinstance(result, PronunciationFeedback)
        result.heard_text = heard_text
        result.target_text = target_text
        result.match_quality = match_quality
        return result, processing_load_signal
