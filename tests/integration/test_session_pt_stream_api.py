from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.main import app


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def test_pause_pt_stream_calls_session_and_returns_status(client, monkeypatch):
    session = client.app.state.copilot.session
    fake_pause = AsyncMock()
    monkeypatch.setattr(session, "pause_portuguese_stream", fake_pause)
    session.status.whisper_pt = "paused"

    response = client.post("/api/session/pause-pt-stream")

    assert response.status_code == 200
    fake_pause.assert_awaited_once()
    assert response.json()["whisper_pt"] == "paused"


def test_resume_pt_stream_calls_session_and_returns_status(client, monkeypatch):
    session = client.app.state.copilot.session
    calls = []
    monkeypatch.setattr(session, "resume_portuguese_stream", lambda: calls.append(True))
    session.status.whisper_pt = "starting"

    response = client.post("/api/session/resume-pt-stream")

    assert response.status_code == 200
    assert calls == [True]
    assert response.json()["whisper_pt"] == "starting"
