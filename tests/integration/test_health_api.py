import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.main import app


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def test_health_reports_missing_whisper_when_binary_absent(client, settings, monkeypatch):
    # whisper_settings fixture already points at a real fake binary/model,
    # so make it look missing for this test.
    settings.whisper.binary_path = "/nonexistent/whisper-stream"
    client.app.state.copilot.settings = settings

    async def fake_ollama_ok(_settings):
        return True

    monkeypatch.setattr("meeting_copilot.api.health.check_ollama_health", fake_ollama_ok)

    response = client.get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert body["components"]["whisper_binary"] == "missing"
    assert body["status"] == "degraded"


def test_health_ok_when_all_present(client, monkeypatch):
    async def fake_ollama_ok(_settings):
        return True

    monkeypatch.setattr("meeting_copilot.api.health.check_ollama_health", fake_ollama_ok)

    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["components"]["whisper_binary"] == "ok"
    assert body["components"]["ollama"] == "ok"
    assert body["privacy"]["audio_persistence"] is False
    assert body["privacy"]["transcript_persistence"] is False


def test_health_reports_ollama_unavailable_without_failing_required_check(client, monkeypatch):
    async def fake_ollama_down(_settings):
        return False

    monkeypatch.setattr("meeting_copilot.api.health.check_ollama_health", fake_ollama_down)

    response = client.get("/api/health")
    # whisper binary/model are present in this fixture, so overall status is
    # still 200 even though Ollama itself is reported unavailable.
    assert response.status_code == 200
    assert response.json()["components"]["ollama"] == "unavailable"
