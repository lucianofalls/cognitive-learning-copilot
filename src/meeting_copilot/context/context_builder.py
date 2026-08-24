"""Assembles the prompt sent to the LLM (section 17).

Order, per spec:
  SYSTEM PROMPT
  + USER PROFILE
  + MEETING CONFIGURATION
  + APPROVED GLOSSARY
  + ACCUMULATED SUMMARY
  + RECENT TRANSCRIPT
  + REQUESTED ACTION

This module builds the `messages` list handed to the Ollama client. It
never truncates the system prompt or action instructions, but it does
bound the summary (via SummaryManager.as_bounded_text) and the recent
transcript (via RollingTranscriptBuffer's own window) so the full session
is never sent to the model.
"""

from __future__ import annotations

from typing import Any

ACTION_PROMPT_NAMES = {
    "explain_context": "explain_context",
    "suggest_answer": "suggest_answer",
    "suggest_question": "suggest_question",
    "disagree_politely": "disagree_politely",
    "request_clarification": "request_clarification",
    "confirm_understanding": "confirm_understanding",
    "explain_english": "explain_english",
}


def _format_profile(profile: dict[str, Any]) -> str:
    user = profile.get("user", {})
    expertise = ", ".join(profile.get("expertise", []))
    prefs = profile.get("answer_preferences", {})
    dimensions = ", ".join(profile.get("analysis_dimensions", []))
    return (
        f"Name: {user.get('name', '')}\n"
        f"Role: {user.get('role', '')}\n"
        f"Native language: {user.get('native_language', '')}\n"
        f"Meeting language: {user.get('meeting_language', '')}\n"
        f"English level: {user.get('english_level', '')}\n"
        f"Expertise: {expertise}\n"
        f"Preferences: {prefs}\n"
        f"Analysis dimensions to prioritize: {dimensions}"
    )


def _format_meeting(meeting: dict[str, Any]) -> str:
    if not meeting:
        return "No meeting configuration was provided for this session."
    lines = [f"Title: {meeting.get('title', '')}", f"Objective: {meeting.get('objective', '')}"]
    if meeting.get("agenda"):
        lines.append("Agenda: " + ", ".join(meeting["agenda"]))
    if meeting.get("expected_topics"):
        lines.append("Expected topics: " + ", ".join(meeting["expected_topics"]))
    if meeting.get("known_systems"):
        lines.append("Known systems: " + ", ".join(meeting["known_systems"]))
    if meeting.get("known_acronyms"):
        lines.append("Known acronyms: " + ", ".join(meeting["known_acronyms"]))
    if meeting.get("desired_outcome"):
        lines.append(f"Desired outcome: {meeting['desired_outcome']}")
    if meeting.get("notes"):
        lines.append(f"Notes: {meeting['notes']}")
    return "\n".join(lines)


def format_glossary_for_prompt(glossary: dict[str, Any]) -> str:
    terms = glossary.get("terms", {})
    if not terms:
        return "No glossary terms configured."
    lines = []
    for term, meta in terms.items():
        expansion = meta.get("expansion") or meta.get("description_pt") or ""
        lines.append(f"- {term}" + (f" ({expansion})" if expansion else ""))
    return "\n".join(lines)


def build_messages(
    *,
    system_prompt: str,
    action_instructions: str,
    action: str,
    profile: dict[str, Any],
    meeting: dict[str, Any],
    glossary: dict[str, Any],
    summary_text: str,
    recent_transcript: str,
    user_idea_pt: str = "",
    processing_load_note: str = "",
) -> list[dict[str, str]]:
    """Build the OpenAI/Ollama-style messages list for one coach action."""
    context_sections = [
        "## User profile",
        _format_profile(profile),
        "",
        "## Meeting configuration",
        _format_meeting(meeting),
        "",
        "## Approved glossary",
        format_glossary_for_prompt(glossary),
        "",
        "## Accumulated summary",
        summary_text or "(empty -- meeting just started)",
        "",
        "## Recent transcript (last rolling window)",
        recent_transcript or "(no speech captured yet)",
    ]
    if user_idea_pt:
        context_sections += ["", "## User's optional idea in Portuguese", user_idea_pt]
    if processing_load_note:
        # Pre-formatted by processing_load_detector.describe_for_prompt --
        # this module stays decoupled from that one (plain string in, same
        # reasoning as every other context_sections entry above).
        context_sections += ["", "## Detected real-time processing load (theory #15)", processing_load_note]

    context_block = "\n".join(context_sections)

    user_message = f"{action_instructions}\n\n{context_block}\n\n## Requested action\n{action}"

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
