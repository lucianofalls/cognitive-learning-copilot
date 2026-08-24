from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from meeting_copilot.services.session_service import SessionService


def _make_session(settings, broadcast=None) -> SessionService:
    return SessionService(settings, broadcast=broadcast or AsyncMock())


@pytest.mark.asyncio
async def test_handle_transcript_text_broadcasts_noticing_flag_on_match(settings):
    """Proactive half of the Noticing Hypothesis (LANGUAGE_COACH_PEDAGOGY.md
    theory #2) -- a real idiom in a new segment should be flagged, not just
    silently reachable via the transcript line's "?" button."""
    broadcast = AsyncMock()
    session = _make_session(settings, broadcast=broadcast)

    await session._handle_transcript_text("Let's circle back on this next week.")

    noticing_calls = [c for c in broadcast.call_args_list if c.args[0] == "noticing.flag"]
    assert len(noticing_calls) == 1
    assert noticing_calls[0].args[1] == {
        "matched_phrase": "circle back",
        "sentence": "Let's circle back on this next week.",
    }


@pytest.mark.asyncio
async def test_handle_transcript_text_does_not_broadcast_without_a_match(settings):
    broadcast = AsyncMock()
    session = _make_session(settings, broadcast=broadcast)

    await session._handle_transcript_text("The deploy finished successfully.")

    assert not any(c.args[0] == "noticing.flag" for c in broadcast.call_args_list)


@pytest.mark.asyncio
async def test_noticing_flag_respects_cooldown(settings):
    """Without a cooldown, a transcript dense with idioms could pulse the
    badge every few seconds -- exactly the ambient/repeated-motion tax
    ADHD_NEUROSCIENCE_REFERENCE.md rule #2 warns against."""
    settings.automation.noticing_cooldown_seconds = 9999
    broadcast = AsyncMock()
    session = _make_session(settings, broadcast=broadcast)

    await session._handle_transcript_text("Let's circle back on this.")
    await session._handle_transcript_text("We should touch base again soon.")

    noticing_calls = [c for c in broadcast.call_args_list if c.args[0] == "noticing.flag"]
    assert len(noticing_calls) == 1
    assert noticing_calls[0].args[1]["matched_phrase"] == "circle back"


@pytest.mark.asyncio
async def test_noticing_flag_fires_again_after_cooldown_elapses(settings):
    settings.automation.noticing_cooldown_seconds = 0
    broadcast = AsyncMock()
    session = _make_session(settings, broadcast=broadcast)

    await session._handle_transcript_text("Let's circle back on this.")
    await session._handle_transcript_text("We should touch base again soon.")

    noticing_calls = [c for c in broadcast.call_args_list if c.args[0] == "noticing.flag"]
    assert len(noticing_calls) == 2


@pytest.mark.asyncio
async def test_noticing_flag_disabled_by_setting(settings):
    settings.automation.detect_noticeable_language = False
    broadcast = AsyncMock()
    session = _make_session(settings, broadcast=broadcast)

    await session._handle_transcript_text("Let's circle back on this.")

    assert not any(c.args[0] == "noticing.flag" for c in broadcast.call_args_list)


def test_delete_session_resets_noticing_cooldown(settings):
    session = _make_session(settings)
    session._last_noticing_broadcast_at = datetime.now().astimezone()

    session.delete_session()

    assert session._last_noticing_broadcast_at is None
