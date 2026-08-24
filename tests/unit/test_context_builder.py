from meeting_copilot.context.context_builder import build_messages


def test_build_messages_includes_all_sections_in_order():
    messages = build_messages(
        system_prompt="SYSTEM_PROMPT_MARKER",
        action_instructions="ACTION_INSTRUCTIONS_MARKER",
        action="suggest_answer",
        profile={"user": {"name": "Alex Silva", "role": "Solution Architect"}, "expertise": ["Kafka"]},
        meeting={"title": "Architecture Review", "expected_topics": ["Kafka", "EKS"]},
        glossary={"terms": {"EKS": {"expansion": "Amazon Elastic Kubernetes Service"}}},
        summary_text="Topic: migration",
        recent_transcript="We should define retries.",
        user_idea_pt="quero dizer que concordo",
    )

    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "SYSTEM_PROMPT_MARKER"

    user_content = messages[1]["content"]
    assert "ACTION_INSTRUCTIONS_MARKER" in user_content
    assert "Alex Silva" in user_content
    assert "Architecture Review" in user_content
    assert "EKS" in user_content
    assert "Topic: migration" in user_content
    assert "We should define retries." in user_content
    assert "quero dizer que concordo" in user_content
    assert user_content.index("Alex Silva") < user_content.index("Architecture Review")
    assert user_content.index("Architecture Review") < user_content.index("Topic: migration")
    assert user_content.index("Topic: migration") < user_content.index("We should define retries.")
    assert user_content.strip().endswith("suggest_answer")


def test_build_messages_handles_empty_meeting_and_summary():
    messages = build_messages(
        system_prompt="SYSTEM",
        action_instructions="INSTRUCTIONS",
        action="explain_context",
        profile={},
        meeting={},
        glossary={},
        summary_text="",
        recent_transcript="",
    )
    user_content = messages[1]["content"]
    assert "No meeting configuration was provided" in user_content
    assert "empty -- meeting just started" in user_content
    assert "no speech captured yet" in user_content
