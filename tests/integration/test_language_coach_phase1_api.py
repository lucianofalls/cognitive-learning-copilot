import pytest
from fastapi.testclient import TestClient

from meeting_copilot.app_state import AppState
from meeting_copilot.context.processing_load_detector import ProcessingLoadSignal
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError
from meeting_copilot.llm.schemas import LanguageCoachExplanation, ScenarioPractice
from meeting_copilot.main import app

_NO_PROCESSING_LOAD_SIGNAL = ProcessingLoadSignal(
    dominant_effort=None, counts={}, segments_analyzed=0, confidence="low"
)


@pytest.fixture
def client(settings):
    with TestClient(app) as test_client:
        test_client.app.state.copilot = AppState(settings)
        yield test_client


def test_ask_rejects_empty_question_and_sentence(client):
    response = client.post("/api/language-coach/ask", json={"question": "", "source_sentence_en": ""})
    assert response.status_code == 422


def test_ask_returns_validated_explanation(client, monkeypatch):
    expected = LanguageCoachExplanation(
        source_sentence_en="We should circle back on this.",
        explanation_pt="'Circle back' significa retomar o assunto depois.",
        native_reasoning_pt="Nativos usam para adiar sem soar rude.",
        alternative_examples=["Let's circle back next week."],
        idiomatic_chunk="circle back",
        follow_up_question_pt="Em que situação você usaria isso?",
    )

    async def fake_explain(profile, session, question="", source_sentence_en=""):
        assert source_sentence_en == "We should circle back on this."
        return expected, _NO_PROCESSING_LOAD_SIGNAL

    monkeypatch.setattr(client.app.state.copilot.language_coach, "explain", fake_explain)

    response = client.post(
        "/api/language-coach/ask",
        json={"question": "", "source_sentence_en": "We should circle back on this."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["idiomatic_chunk"] == "circle back"
    assert "retomar" in body["explanation_pt"]
    assert body["processing_load"] is None


def test_ask_returns_503_when_ollama_unavailable(client, monkeypatch):
    async def fake_explain(*args, **kwargs):
        raise OllamaUnavailableError("connection refused")

    monkeypatch.setattr(client.app.state.copilot.language_coach, "explain", fake_explain)

    response = client.post("/api/language-coach/ask", json={"question": "why?"})
    assert response.status_code == 503
    assert "modelo local" in response.json()["detail"]


def test_ask_returns_502_on_invalid_model_output(client, monkeypatch):
    async def fake_explain(*args, **kwargs):
        raise OllamaInvalidResponseError("bad json")

    monkeypatch.setattr(client.app.state.copilot.language_coach, "explain", fake_explain)

    response = client.post("/api/language-coach/ask", json={"question": "why?"})
    assert response.status_code == 502


def test_scenario_returns_validated_practice(client, monkeypatch):
    expected = ScenarioPractice(
        scenario_pt="Você está numa reunião de arquitetura e o time discorda do seu plano.",
        scenario_prompt_en="I'm not convinced this will scale -- can we circle back on it?",
        target_pattern="circle back",
    )

    async def fake_scenario(profile, session, target_pattern):
        assert target_pattern == "circle back"
        return expected, _NO_PROCESSING_LOAD_SIGNAL

    monkeypatch.setattr(client.app.state.copilot.language_coach, "scenario", fake_scenario)

    response = client.post("/api/language-coach/scenario", json={"target_pattern": "circle back"})
    assert response.status_code == 200
    body = response.json()
    assert body["target_pattern"] == "circle back"
    assert "circle back" in body["scenario_prompt_en"]
    assert body["processing_load"] is None


def test_scenario_returns_503_when_ollama_unavailable(client, monkeypatch):
    async def fake_scenario(*args, **kwargs):
        raise OllamaUnavailableError("connection refused")

    monkeypatch.setattr(client.app.state.copilot.language_coach, "scenario", fake_scenario)

    response = client.post("/api/language-coach/scenario", json={"target_pattern": "circle back"})
    assert response.status_code == 503


def test_scenario_requires_target_pattern_field(client):
    response = client.post("/api/language-coach/scenario", json={})
    assert response.status_code == 422


def test_ask_and_scenario_share_coach_busy_count_gate(client, monkeypatch):
    """`_call_coach` increments/decrements the same counter api/actions.py's
    `_run` uses -- confirms the refactor into a shared helper preserved that,
    since a leaked increment would leave later coach actions permanently
    reporting busy."""
    session = client.app.state.copilot.session
    assert session.coach_busy_count == 0

    async def fake_scenario(profile, session_arg, target_pattern):
        assert session.coach_busy_count == 1
        return ScenarioPractice(scenario_pt="x", scenario_prompt_en="y", target_pattern=target_pattern), (
            _NO_PROCESSING_LOAD_SIGNAL
        )

    monkeypatch.setattr(client.app.state.copilot.language_coach, "scenario", fake_scenario)

    response = client.post("/api/language-coach/scenario", json={"target_pattern": "circle back"})
    assert response.status_code == 200
    assert session.coach_busy_count == 0


def test_pronunciation_guide_rejects_empty_text(client):
    response = client.post("/api/language-coach/pronunciation-guide", json={"source_text_en": "   "})
    assert response.status_code == 422


def test_pronunciation_guide_returns_deterministic_respelling(client):
    """Not mocked -- this endpoint is a pure CMU-dictionary lookup with no
    Ollama call at all (see context/pronunciation_guide.py), so there's
    nothing to fake; the real function should just work."""
    response = client.post("/api/language-coach/pronunciation-guide", json={"source_text_en": "though"})
    assert response.status_code == 200
    body = response.json()
    assert body["source_text_en"] == "though"
    assert body["phonetic_respelling_pt"] == "d-ôu"
    assert body["stress_note_pt"]


def test_pronunciation_guide_leaves_unknown_words_unchanged(client):
    response = client.post(
        "/api/language-coach/pronunciation-guide", json={"source_text_en": "the Kubernetes rollout"}
    )
    assert response.status_code == 200
    assert "Kubernetes" in response.json()["phonetic_respelling_pt"]
