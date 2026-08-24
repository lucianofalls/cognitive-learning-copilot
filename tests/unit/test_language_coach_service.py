import pytest

from meeting_copilot.llm.schemas import LanguageCoachExplanation, ScenarioPractice
from meeting_copilot.models import TranscriptSegment
from meeting_copilot.services import language_coach_service as language_coach_service_module
from meeting_copilot.services.language_coach_service import LanguageCoachService
from meeting_copilot.services.session_service import SessionService


def _make_session(settings) -> SessionService:
    return SessionService(settings)


def _seed_memory_strain(session: SessionService) -> None:
    """Two long gaps between consecutive segments is the Memory Effort
    signal (theory #15b, DEFAULT_MEMORY_GAP_SECONDS=3.5s) -- >= 2 hits
    needed to clear ProcessingLoadDetector's dominant-effort threshold."""
    from datetime import timedelta

    base = TranscriptSegment(text="We need to", normalized_text="we need to", stable=True)
    later = TranscriptSegment(
        text="finalize the retry policy",
        normalized_text="finalize the retry policy",
        stable=True,
        created_at=base.created_at + timedelta(seconds=5),
    )
    third = TranscriptSegment(
        text="before the release",
        normalized_text="before the release",
        stable=True,
        created_at=later.created_at + timedelta(seconds=5),
    )
    session.rolling_buffer.add(base)
    session.rolling_buffer.add(later)
    session.rolling_buffer.add(third)


@pytest.mark.asyncio
async def test_explain_includes_processing_load_note_when_signal_detected(settings, monkeypatch):
    session = _make_session(settings)
    _seed_memory_strain(session)

    captured = {}

    async def fake_call_and_validate(messages, model_cls, settings_arg):
        captured["messages"] = messages
        return LanguageCoachExplanation(
            explanation_pt="x", native_reasoning_pt="y", follow_up_question_pt="z"
        )

    monkeypatch.setattr(language_coach_service_module, "call_and_validate", fake_call_and_validate)

    service = LanguageCoachService(settings.ollama)
    _result, signal = await service.explain({}, session, question="why?")

    assert signal.dominant_effort == "memory"
    assert "Detected real-time processing load" in captured["messages"][1]["content"]
    assert "Memory" in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_scenario_omits_processing_load_section_with_no_evidence(settings, monkeypatch):
    session = _make_session(settings)

    async def fake_call_and_validate(messages, model_cls, settings_arg):
        return ScenarioPractice(scenario_pt="x", scenario_prompt_en="y", target_pattern="circle back")

    monkeypatch.setattr(language_coach_service_module, "call_and_validate", fake_call_and_validate)

    service = LanguageCoachService(settings.ollama)
    _result, signal = await service.scenario({}, session, "circle back")

    assert signal.dominant_effort is None
