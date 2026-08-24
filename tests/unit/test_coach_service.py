import pytest

from meeting_copilot.llm.schemas import MeetingCoachResponse
from meeting_copilot.models import TranscriptSegment
from meeting_copilot.services import coach_service as coach_service_module
from meeting_copilot.services.coach_service import CoachService
from meeting_copilot.services.session_service import SessionService


def _make_session(settings) -> SessionService:
    return SessionService(settings)


@pytest.mark.asyncio
async def test_run_action_includes_processing_load_note_when_signal_detected(settings, monkeypatch):
    """ProcessingLoadDetector (LANGUAGE_COACH_PEDAGOGY.md theory #15) should
    be consulted on every coach action and, when it names a dominant
    effort, that should reach the LLM prompt -- not just sit unused."""
    session = _make_session(settings)
    # Three segments each carrying a self-correction marker -> Production
    # Effort strain, per test_processing_load_detector.py's own fixtures
    # for _RESTART_MARKERS.
    for _ in range(3):
        session.rolling_buffer_pt.add(
            TranscriptSegment(text="i mean, let me rephrase", normalized_text="i mean, let me rephrase", stable=True)
        )

    captured = {}

    async def fake_call_and_validate(messages, model_cls, settings_arg):
        captured["messages"] = messages
        return MeetingCoachResponse(action="suggest_answer", confidence="high")

    monkeypatch.setattr(coach_service_module, "call_and_validate", fake_call_and_validate)

    service = CoachService(settings.ollama)
    result, signal = await service.run_action("suggest_answer", session, profile={}, glossary={})

    assert isinstance(result, MeetingCoachResponse)
    assert signal.dominant_effort == "production"
    user_message = captured["messages"][1]["content"]
    assert "Detected real-time processing load" in user_message
    assert "Production" in user_message


@pytest.mark.asyncio
async def test_run_action_omits_processing_load_section_with_no_evidence(settings, monkeypatch):
    session = _make_session(settings)
    captured = {}

    async def fake_call_and_validate(messages, model_cls, settings_arg):
        captured["messages"] = messages
        return MeetingCoachResponse(action="suggest_answer", confidence="high")

    monkeypatch.setattr(coach_service_module, "call_and_validate", fake_call_and_validate)

    service = CoachService(settings.ollama)
    _result, signal = await service.run_action("suggest_answer", session, profile={}, glossary={})

    assert signal.dominant_effort is None
    assert "Detected real-time processing load" not in captured["messages"][1]["content"]


@pytest.mark.asyncio
async def test_run_action_analyzes_both_forward_and_reverse_buffers(settings, monkeypatch):
    """Combining both pipelines was an explicit choice (the real-time
    processing difficulties this detector watches for span both
    understanding English and producing it) -- a signal that only shows
    up in the forward buffer must still be picked up."""
    session = _make_session(settings)
    for _ in range(3):
        session.rolling_buffer.add(
            TranscriptSegment(
                text="can you repeat that, please", normalized_text="can you repeat that, please", stable=True
            )
        )

    async def fake_call_and_validate(messages, model_cls, settings_arg):
        return MeetingCoachResponse(action="suggest_answer", confidence="high")

    monkeypatch.setattr(coach_service_module, "call_and_validate", fake_call_and_validate)

    service = CoachService(settings.ollama)
    _result, signal = await service.run_action("suggest_answer", session, profile={}, glossary={})

    assert signal.dominant_effort == "listening_analysis"
