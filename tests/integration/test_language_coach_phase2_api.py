import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.context.spaced_repetition import LearningItemStore
from meeting_copilot.context.tts import SpeechSynthesisError
from meeting_copilot.main import app


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def test_speak_returns_audio_bytes(client, monkeypatch):
    async def fake_synthesize(text, voice="Daniel"):
        assert text == "circle back"
        return b"RIFF....WAVEfake"

    monkeypatch.setattr("meeting_copilot.api.language_coach.synthesize_speech", fake_synthesize)

    response = client.post("/api/language-coach/speak", json={"text": "circle back"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF....WAVEfake"


def test_speak_returns_502_on_synthesis_error(client, monkeypatch):
    async def fake_synthesize(text, voice="Daniel"):
        raise SpeechSynthesisError("say exited non-zero")

    monkeypatch.setattr("meeting_copilot.api.language_coach.synthesize_speech", fake_synthesize)

    response = client.post("/api/language-coach/speak", json={"text": "circle back"})
    assert response.status_code == 502


def test_review_queue_reports_disabled_when_persistence_off(client):
    # `settings` fixture defaults privacy.persist_learning_notes to False, so
    # AppState should never have constructed a LearningItemStore.
    assert client.app.state.copilot.learning_items is None

    response = client.get("/api/language-coach/review-queue")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "items": []}


def test_add_learning_item_returns_503_when_persistence_off(client):
    response = client.post(
        "/api/language-coach/learning-items",
        json={"content_en": "circle back", "context_sentence": "We should circle back."},
    )
    assert response.status_code == 503


def test_review_result_returns_503_when_persistence_off(client):
    response = client.post(
        "/api/language-coach/review-result",
        json={"item_id": "abc123", "recalled": True},
    )
    assert response.status_code == 503


def test_add_and_review_roundtrip_when_persistence_enabled(client, tmp_path):
    client.app.state.copilot.learning_items = LearningItemStore(tmp_path / "learning_items")

    add_response = client.post(
        "/api/language-coach/learning-items",
        json={"content_en": "circle back", "context_sentence": "We should circle back on this."},
    )
    assert add_response.status_code == 200
    item = add_response.json()
    assert item["content_en"] == "circle back"
    assert item["review_count"] == 0

    queue_response = client.get("/api/language-coach/review-queue")
    assert queue_response.status_code == 200
    queue_body = queue_response.json()
    assert queue_body["enabled"] is True
    assert len(queue_body["items"]) == 1
    assert queue_body["items"][0]["id"] == item["id"]

    review_response = client.post(
        "/api/language-coach/review-result",
        json={"item_id": item["id"], "recalled": True},
    )
    assert review_response.status_code == 200
    assert review_response.json()["review_count"] == 1

    # Just reviewed -> rescheduled into the future -> no longer due today.
    queue_after = client.get("/api/language-coach/review-queue").json()
    assert queue_after["items"] == []


def test_review_result_returns_404_for_unknown_item(client, tmp_path):
    client.app.state.copilot.learning_items = LearningItemStore(tmp_path / "learning_items")

    response = client.post(
        "/api/language-coach/review-result",
        json={"item_id": "nonexistent", "recalled": True},
    )
    assert response.status_code == 404


def test_add_learning_item_rejects_empty_content(client, tmp_path):
    client.app.state.copilot.learning_items = LearningItemStore(tmp_path / "learning_items")

    response = client.post(
        "/api/language-coach/learning-items",
        json={"content_en": "  ", "context_sentence": ""},
    )
    assert response.status_code == 422
