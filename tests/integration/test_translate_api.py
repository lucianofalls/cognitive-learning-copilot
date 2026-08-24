import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.context.pt_speech import PortugueseSpeechError
from meeting_copilot.main import app


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def _post(client, audio_bytes=b"fake-wav-bytes"):
    return client.post(
        "/api/translate/speak-portuguese",
        files={"audio": ("attempt.wav", audio_bytes, "audio/wav")},
    )


def test_speak_portuguese_returns_heard_text_and_translation(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        assert audio_bytes == b"fake-wav-bytes"
        return "Bom dia, vamos começar a reunião."

    async def fake_translate(text, model_dir):
        assert text == "Bom dia, vamos começar a reunião."
        return "Good morning, let's start the meeting."

    monkeypatch.setattr("meeting_copilot.api.translate.transcribe_portuguese", fake_transcribe)
    monkeypatch.setattr("meeting_copilot.api.translate.translate_pt_to_en", fake_translate)

    response = _post(client)
    assert response.status_code == 200
    body = response.json()
    assert body["heard_pt"] == "Bom dia, vamos começar a reunião."
    assert body["translated_en"] == "Good morning, let's start the meeting."


def test_speak_portuguese_rejects_empty_audio(client):
    response = _post(client, audio_bytes=b"")
    assert response.status_code == 422


def test_speak_portuguese_returns_502_on_transcription_error(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        raise PortugueseSpeechError("whisper-cli exited with a non-zero status.")

    monkeypatch.setattr("meeting_copilot.api.translate.transcribe_portuguese", fake_transcribe)

    response = _post(client)
    assert response.status_code == 502


def test_speak_portuguese_skips_translation_when_nothing_was_heard(client, monkeypatch):
    async def fake_transcribe(audio_bytes, whisper_settings):
        return "   "

    translate_called = False

    async def fake_translate(text, model_dir):
        nonlocal translate_called
        translate_called = True
        return "should not be called"

    monkeypatch.setattr("meeting_copilot.api.translate.transcribe_portuguese", fake_transcribe)
    monkeypatch.setattr("meeting_copilot.api.translate.translate_pt_to_en", fake_translate)

    response = _post(client)
    assert response.status_code == 200
    body = response.json()
    assert body == {"heard_pt": "", "translated_en": ""}
    assert translate_called is False


def test_detect_language_route_pt(client):
    response = client.post("/api/translate/detect-language", json={"text": "quero dizer que concordamos"})
    assert response.status_code == 200
    assert response.json() == {"language": "pt"}


def test_detect_language_route_en(client):
    response = client.post("/api/translate/detect-language", json={"text": "we should push the deadline"})
    assert response.status_code == 200
    assert response.json() == {"language": "en"}


def test_translate_en_to_pt_route(client, monkeypatch):
    async def fake_translate(text, model_dir, glossary_terms=()):
        assert text == "we agree, but need to define the retry"
        return "concordamos, mas precisamos definir o retry"

    monkeypatch.setattr("meeting_copilot.api.translate.translate_en_to_pt_br", fake_translate)

    response = client.post(
        "/api/translate/en-to-pt", json={"text": "we agree, but need to define the retry"}
    )
    assert response.status_code == 200
    assert response.json() == {"translated_pt": "concordamos, mas precisamos definir o retry"}


def test_translate_en_to_pt_route_rejects_empty_text(client):
    response = client.post("/api/translate/en-to-pt", json={"text": "   "})
    assert response.status_code == 422
