import pytest
from pydantic import ValidationError

from meeting_copilot.llm.schemas import MeetingCoachResponse, response_json_schema


def test_valid_response_parses():
    response = MeetingCoachResponse(
        action="suggest_answer",
        context_pt="A equipe está discutindo retries.",
        suggested_answer_en="I agree, but we should define a common retry policy first.",
        confidence="high",
    )
    assert response.action == "suggest_answer"
    assert response.insufficient_context is False


def test_missing_confidence_is_rejected():
    with pytest.raises(ValidationError):
        MeetingCoachResponse(action="suggest_answer")


def test_invalid_action_is_rejected():
    with pytest.raises(ValidationError):
        MeetingCoachResponse(action="not_a_real_action", confidence="low")


def test_key_vocabulary_max_length_enforced():
    with pytest.raises(ValidationError):
        MeetingCoachResponse(
            action="explain_english",
            confidence="medium",
            key_vocabulary=["one", "two", "three", "four"],
        )


def test_response_json_schema_has_required_fields():
    schema = response_json_schema()
    assert schema["properties"]["action"]
    assert "confidence" in schema["required"]
