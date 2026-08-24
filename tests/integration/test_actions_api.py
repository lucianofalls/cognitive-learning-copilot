import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.context.processing_load_detector import ProcessingLoadSignal
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError
from meeting_copilot.llm.schemas import MeetingCoachResponse
from meeting_copilot.main import app

_NO_PROCESSING_LOAD_SIGNAL = ProcessingLoadSignal(
    dominant_effort=None, counts={}, segments_analyzed=0, confidence="low"
)


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def test_suggest_answer_returns_validated_response(client, monkeypatch):
    expected = MeetingCoachResponse(
        action="suggest_answer",
        context_pt="A equipe discute retries.",
        suggested_answer_en="I agree, but let's define a common retry policy first.",
        confidence="high",
    )

    async def fake_run_action(action, session, profile, glossary, user_idea_pt=""):
        return expected, _NO_PROCESSING_LOAD_SIGNAL

    monkeypatch.setattr(client.app.state.copilot.coach, "run_action", fake_run_action)

    response = client.post("/api/actions/suggest-answer", json={"idea_pt": ""})
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "suggest_answer"
    assert body["confidence"] == "high"
    assert "retry policy" in body["suggested_answer_en"]
    assert body["processing_load"] is None


def test_action_returns_503_when_ollama_unavailable(client, monkeypatch):
    async def fake_run_action(*args, **kwargs):
        raise OllamaUnavailableError("connection refused")

    monkeypatch.setattr(client.app.state.copilot.coach, "run_action", fake_run_action)

    response = client.post("/api/actions/explain-context", json={})
    assert response.status_code == 503
    assert "modelo local" in response.json()["detail"]


def test_action_returns_502_on_invalid_model_output(client, monkeypatch):
    async def fake_run_action(*args, **kwargs):
        raise OllamaInvalidResponseError("bad json")

    monkeypatch.setattr(client.app.state.copilot.coach, "run_action", fake_run_action)

    response = client.post("/api/actions/suggest-question", json={})
    assert response.status_code == 502
