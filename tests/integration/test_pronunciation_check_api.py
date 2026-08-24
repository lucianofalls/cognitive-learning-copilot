import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.context.pronunciation import PronunciationCheckError, PronunciationTranscription
from meeting_copilot.context.processing_load_detector import ProcessingLoadSignal
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError
from meeting_copilot.llm.schemas import PronunciationFeedback
from meeting_copilot.main import app

_NO_PROCESSING_LOAD_SIGNAL = ProcessingLoadSignal(
    dominant_effort=None, counts={}, segments_analyzed=0, confidence="low"
)


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def _post(client, target_text="circle back", audio_bytes=b"fake-wav-bytes"):
    return client.post(
        "/api/language-coach/pronunciation-check",
        data={"target_text": target_text},
        files={"audio": ("attempt.wav", audio_bytes, "audio/wav")},
    )


def test_pronunciation_check_returns_validated_feedback(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        assert audio_bytes == b"fake-wav-bytes"
        return PronunciationTranscription(heard_text="circle back", low_confidence_words=[])

    async def fake_pronunciation_feedback(profile, session, heard_text, target_text, match_quality, low_confidence_words):
        return (
            PronunciationFeedback(
                heard_text=heard_text,
                target_text=target_text,
                match_quality=match_quality,
                specific_feedback_pt="Saiu bem parecido com o esperado.",
                encouragement_pt="Continue praticando, você está indo bem!",
            ),
            _NO_PROCESSING_LOAD_SIGNAL,
        )

    monkeypatch.setattr("meeting_copilot.api.language_coach.transcribe_attempt", fake_transcribe)
    monkeypatch.setattr(client.app.state.copilot.language_coach, "pronunciation_feedback", fake_pronunciation_feedback)

    response = _post(client)
    assert response.status_code == 200
    body = response.json()
    assert body["heard_text"] == "circle back"
    assert body["match_quality"] == "close"
    assert body["encouragement_pt"]
    assert body["processing_load"] is None


def test_pronunciation_check_rejects_empty_target_text(client):
    response = _post(client, target_text="   ")
    assert response.status_code == 422


def test_pronunciation_check_returns_502_on_transcription_error(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        raise PronunciationCheckError("whisper-cli exited with a non-zero status.")

    monkeypatch.setattr("meeting_copilot.api.language_coach.transcribe_attempt", fake_transcribe)

    response = _post(client)
    assert response.status_code == 502


def test_pronunciation_check_returns_503_when_ollama_unavailable(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        return PronunciationTranscription(heard_text="circle back", low_confidence_words=[])

    async def fake_pronunciation_feedback(*args, **kwargs):
        raise OllamaUnavailableError("connection refused")

    monkeypatch.setattr("meeting_copilot.api.language_coach.transcribe_attempt", fake_transcribe)
    monkeypatch.setattr(client.app.state.copilot.language_coach, "pronunciation_feedback", fake_pronunciation_feedback)

    response = _post(client)
    assert response.status_code == 503


def test_pronunciation_check_returns_502_on_invalid_model_output(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        return PronunciationTranscription(heard_text="circle back", low_confidence_words=[])

    async def fake_pronunciation_feedback(*args, **kwargs):
        raise OllamaInvalidResponseError("bad json")

    monkeypatch.setattr("meeting_copilot.api.language_coach.transcribe_attempt", fake_transcribe)
    monkeypatch.setattr(client.app.state.copilot.language_coach, "pronunciation_feedback", fake_pronunciation_feedback)

    response = _post(client)
    assert response.status_code == 502
