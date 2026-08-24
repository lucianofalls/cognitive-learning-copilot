"""Ollama-backed callables injected into TranslationManager/SummaryManager.

Kept separate from SessionService (which stays Ollama-agnostic by design,
see its module docstring) and from CoachService (which handles the 7
on-demand coach actions, not the periodic background refresh). Both
functions here are built as closures over a glossary getter so they
always see the current glossary even if it's edited mid-session via the
API.
"""

from __future__ import annotations

from collections.abc import Callable

from meeting_copilot.config import OllamaSettings, TranslationSettings
from meeting_copilot.context.argos_translate import translate_en_to_pt
from meeting_copilot.context.opus_mt import translate_en_to_pt_br
from meeting_copilot.context.context_builder import format_glossary_for_prompt
from meeting_copilot.llm.ollama_client import call_and_validate
from meeting_copilot.llm.prompt_loader import get_summarize_prompt, get_translate_prompt
from meeting_copilot.llm.schemas import MeetingSummaryLLMResponse, TranslationLLMResponse
from meeting_copilot.models import MeetingSummary

GlossaryProvider = Callable[[], dict]


def make_translate_fn(
    ollama_settings: OllamaSettings,
    glossary_provider: GlossaryProvider,
    engine: str = "argos",
    translation_model: str = "",
    translation_settings: TranslationSettings | None = None,
):
    """Build the translate_fn TranslationManager.refresh calls.

    engine="argos": dedicated local NMT, not an LLM -- see
    context/argos_translate.py's module docstring and docs/DECISIONS.md,
    2026-07-20. Fast, but its only en->pt package is European
    Portuguese, not Brazilian (confirmed 2026-07-22).

    engine="opus_mt" (recommended default going forward): Helsinki-NLP
    OPUS-MT models, same CTranslate2 engine as argos but with a real
    Brazilian-Portuguese target (`>>pob<<` tag) -- see
    context/opus_mt.py.

    engine="ollama": the original LLM path, kept for language pairs
    neither NMT option covers, or if a future model turns out reliable
    enough to be worth Ollama's overhead.
    """
    if engine == "opus_mt":
        assert translation_settings is not None, "opus_mt engine requires translation_settings"
        return _make_opus_mt_translate_fn(glossary_provider, translation_settings.opus_mt_en_pt_dir_expanded)
    if engine == "argos":
        return _make_argos_translate_fn(glossary_provider)
    return _make_ollama_translate_fn(ollama_settings, glossary_provider, translation_model)


def _make_argos_translate_fn(glossary_provider: GlossaryProvider):
    async def translate_fn(text: str) -> str:
        glossary_terms = tuple(glossary_provider().get("terms", {}).keys())
        return await translate_en_to_pt(text, glossary_terms)

    return translate_fn


def _make_opus_mt_translate_fn(glossary_provider: GlossaryProvider, model_dir):
    async def translate_fn(text: str) -> str:
        glossary_terms = tuple(glossary_provider().get("terms", {}).keys())
        return await translate_en_to_pt_br(text, model_dir, glossary_terms)

    return translate_fn


def _make_ollama_translate_fn(
    ollama_settings: OllamaSettings,
    glossary_provider: GlossaryProvider,
    translation_model: str,
):
    settings = ollama_settings.model_copy(update={"model": translation_model}) if translation_model else ollama_settings

    async def translate_fn(text: str) -> str:
        messages = [
            {"role": "system", "content": get_translate_prompt()},
            {
                "role": "user",
                "content": (
                    f"## Approved glossary\n{format_glossary_for_prompt(glossary_provider())}\n\n"
                    f"## English excerpt to translate\n{text}"
                ),
            },
        ]
        result = await call_and_validate(messages, TranslationLLMResponse, settings)
        assert isinstance(result, TranslationLLMResponse)
        return result.translated_pt

    return translate_fn


def make_summarize_fn(ollama_settings: OllamaSettings):
    # Empirically, this model+grammar combination collapses to an
    # all-empty summary noticeably more often at the coach actions'
    # temperature (0.2) than at 0.6 -- verified by running the same input
    # repeatedly. Coach actions need low temperature for consistent
    # phrasing; the summary extraction doesn't, so it gets its own value
    # rather than raising the shared default.
    summarize_settings = ollama_settings.model_copy(update={"temperature": 0.6})

    async def summarize_fn(current: MeetingSummary, new_text: str) -> MeetingSummary:
        messages = [
            {"role": "system", "content": get_summarize_prompt()},
            {
                "role": "user",
                "content": (
                    f"## Existing summary\n{current.model_dump_json()}\n\n"
                    f"## New transcript text\n{new_text}"
                ),
            },
        ]
        result = await call_and_validate(messages, MeetingSummaryLLMResponse, summarize_settings)
        assert isinstance(result, MeetingSummaryLLMResponse)
        return MeetingSummary(**result.model_dump())

    return summarize_fn
