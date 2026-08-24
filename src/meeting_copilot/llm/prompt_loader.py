"""Thin cache around meeting_copilot.config.load_prompt for the 7 action prompts."""

from __future__ import annotations

from functools import lru_cache

from meeting_copilot.config import load_prompt


@lru_cache(maxsize=None)
def get_system_prompt() -> str:
    return load_prompt("system_prompt")


@lru_cache(maxsize=None)
def get_action_prompt(action: str) -> str:
    return load_prompt(action)


@lru_cache(maxsize=None)
def get_translate_prompt() -> str:
    return load_prompt("translate")


@lru_cache(maxsize=None)
def get_summarize_prompt() -> str:
    return load_prompt("summarize")


@lru_cache(maxsize=None)
def get_language_coach_system_prompt() -> str:
    return load_prompt("language_coach_system")


@lru_cache(maxsize=None)
def get_language_coach_explain_prompt() -> str:
    return load_prompt("language_coach_explain")


@lru_cache(maxsize=None)
def get_language_coach_scenario_prompt() -> str:
    return load_prompt("language_coach_scenario")


@lru_cache(maxsize=None)
def get_language_coach_pronunciation_prompt() -> str:
    return load_prompt("language_coach_pronunciation")
