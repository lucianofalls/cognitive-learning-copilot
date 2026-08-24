from unittest.mock import AsyncMock

import pytest

from meeting_copilot.models import TranscriptSegment
from meeting_copilot.services.session_service import SessionService


def _make_session(settings, translate_pt_en_fn=None, broadcast=None):
    return SessionService(
        settings,
        broadcast=broadcast or AsyncMock(),
        translate_pt_en_fn=translate_pt_en_fn,
    )


def test_portuguese_stream_disabled_when_flag_is_false(settings, tmp_path):
    settings.whisper.enable_portuguese_stream = False
    session = _make_session(settings, translate_pt_en_fn=AsyncMock(return_value="hi"))

    session._start_portuguese_stream()

    assert session.status.whisper_pt == "disabled"
    assert session._whisper_pt is None


def test_portuguese_stream_disabled_when_no_translate_fn_provided(settings):
    settings.whisper.enable_portuguese_stream = True
    session = _make_session(settings, translate_pt_en_fn=None)

    session._start_portuguese_stream()

    assert session.status.whisper_pt == "disabled"
    assert session._whisper_pt is None


def test_portuguese_stream_disabled_when_multilingual_model_missing(settings, tmp_path):
    settings.whisper.enable_portuguese_stream = True
    settings.whisper.multilingual_model_path = str(tmp_path / "nonexistent-model.bin")
    session = _make_session(settings, translate_pt_en_fn=AsyncMock(return_value="hi"))

    session._start_portuguese_stream()

    assert session.status.whisper_pt == "disabled"
    assert session._whisper_pt is None


def test_portuguese_stream_disabled_when_translation_model_dir_missing(settings, tmp_path):
    settings.whisper.enable_portuguese_stream = True
    fake_model = tmp_path / "ggml-small.bin"
    fake_model.write_bytes(b"fake")
    settings.whisper.multilingual_model_path = str(fake_model)
    settings.translation.opus_mt_pt_en_dir = str(tmp_path / "nonexistent-opus-mt-dir")
    session = _make_session(settings, translate_pt_en_fn=AsyncMock(return_value="hi"))

    session._start_portuguese_stream()

    assert session.status.whisper_pt == "disabled"
    assert session._whisper_pt is None


@pytest.mark.asyncio
async def test_portuguese_stream_starts_when_everything_present(settings, tmp_path):
    settings.whisper.enable_portuguese_stream = True
    fake_model = tmp_path / "ggml-small.bin"
    fake_model.write_bytes(b"fake")
    settings.whisper.multilingual_model_path = str(fake_model)
    opus_mt_dir = tmp_path / "opus-mt-pt-en"
    opus_mt_dir.mkdir()
    settings.translation.opus_mt_pt_en_dir = str(opus_mt_dir)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock(return_value="hi"))

    session._start_portuguese_stream()

    assert session.status.whisper_pt == "starting"
    assert session._whisper_pt is not None
    # Uses the multilingual model + "pt", never the main English settings --
    # confirms the two whisper processes are genuinely configured
    # independently, not accidentally sharing settings.
    assert session._whisper_pt._settings.model_path == str(fake_model)
    assert session._whisper_pt._settings.language == "pt"
    assert session.settings.whisper.model_path != str(fake_model)

    session._consume_task_pt.cancel()


@pytest.mark.asyncio
async def test_handle_transcript_text_pt_feeds_rolling_buffer_pt(settings):
    """Added 2026-07-23 alongside ProcessingLoadDetector -- the reverse
    pipeline needs its own segment history (with real timestamps), not
    just translation_manager_pt's plain pending-text accumulator, so the
    detector's pause/self-correction heuristics have something to look
    at (see recent_segments_for_processing_load below)."""
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    assert len(session.rolling_buffer_pt) == 0

    await session._handle_transcript_text_pt("Bom dia")

    assert len(session.rolling_buffer_pt) == 1
    assert session.rolling_buffer_pt.recent_segments()[0].text == "Bom dia"


def test_recent_segments_for_processing_load_merges_and_sorts_both_buffers(settings):
    from datetime import timedelta

    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    t0 = TranscriptSegment(text="forward first", normalized_text="forward first", stable=True)
    t2 = TranscriptSegment(
        text="forward second", normalized_text="forward second", stable=True, created_at=t0.created_at + timedelta(seconds=4)
    )
    t1 = TranscriptSegment(
        text="reverse middle", normalized_text="reverse middle", stable=True, created_at=t0.created_at + timedelta(seconds=2)
    )
    session.rolling_buffer.add(t0)
    session.rolling_buffer.add(t2)
    session.rolling_buffer_pt.add(t1)

    merged = session.recent_segments_for_processing_load()

    assert [segment.text for segment in merged] == ["forward first", "reverse middle", "forward second"]


@pytest.mark.asyncio
async def test_delete_session_clears_rolling_buffer_pt(settings):
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    await session._handle_transcript_text_pt("Bom dia")
    assert len(session.rolling_buffer_pt) == 1

    session.delete_session()

    assert len(session.rolling_buffer_pt) == 0


@pytest.mark.asyncio
async def test_handle_transcript_text_pt_broadcasts_and_translates(settings):
    broadcast = AsyncMock()
    translate_fn = AsyncMock(return_value="Good morning")
    session = _make_session(settings, translate_pt_en_fn=translate_fn, broadcast=broadcast)

    await session._handle_transcript_text_pt("Bom dia")
    # translation fires via asyncio.create_task -- give it a tick to run.
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    broadcast.assert_any_call("transcript_pt.segment", {"text": "Bom dia"})


@pytest.mark.asyncio
async def test_handle_transcript_text_pt_dedupes_exact_repeats(settings):
    broadcast = AsyncMock()
    session = _make_session(settings, translate_pt_en_fn=AsyncMock(), broadcast=broadcast)

    await session._handle_transcript_text_pt("Bom dia")
    await session._handle_transcript_text_pt("Bom dia")

    segment_calls = [c for c in broadcast.call_args_list if c.args[0] == "transcript_pt.segment"]
    assert len(segment_calls) == 1


@pytest.mark.asyncio
async def test_refresh_translation_pt_broadcasts_english(settings):
    broadcast = AsyncMock()
    translate_fn = AsyncMock(return_value="Good morning everyone")
    session = _make_session(settings, translate_pt_en_fn=translate_fn, broadcast=broadcast)
    session.translation_manager_pt.add_stable_text("Bom dia pessoal")

    await session._refresh_translation_pt()

    broadcast.assert_any_call("translation_en.update", {"text_en": "Good morning everyone"})


@pytest.mark.asyncio
async def test_refresh_translation_pt_survives_translate_fn_error(settings):
    broadcast = AsyncMock()
    translate_fn = AsyncMock(side_effect=RuntimeError("model file missing"))
    session = _make_session(settings, translate_pt_en_fn=translate_fn, broadcast=broadcast)
    session.translation_manager_pt.add_stable_text("Bom dia")

    await session._refresh_translation_pt()  # must not raise

    assert not any(c.args[0] == "translation_en.update" for c in broadcast.call_args_list)


@pytest.mark.asyncio
async def test_stop_resets_running_pt_stream_to_stopped_not_disabled(settings, tmp_path):
    settings.whisper.enable_portuguese_stream = True
    fake_model = tmp_path / "ggml-small.bin"
    fake_model.write_bytes(b"fake")
    settings.whisper.multilingual_model_path = str(fake_model)
    opus_mt_dir = tmp_path / "opus-mt-pt-en"
    opus_mt_dir.mkdir()
    settings.translation.opus_mt_pt_en_dir = str(opus_mt_dir)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())

    session._start_portuguese_stream()
    assert session.status.whisper_pt == "starting"

    await session.stop()

    assert session.status.whisper_pt == "stopped"
    assert session._whisper_pt is None


@pytest.mark.asyncio
async def test_stop_leaves_disabled_pt_stream_as_disabled(settings):
    settings.whisper.enable_portuguese_stream = False
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    session._start_portuguese_stream()
    assert session.status.whisper_pt == "disabled"

    await session.stop()

    assert session.status.whisper_pt == "disabled"


def _enable_pt_stream(settings, tmp_path):
    settings.whisper.enable_portuguese_stream = True
    fake_model = tmp_path / "ggml-small.bin"
    fake_model.write_bytes(b"fake")
    settings.whisper.multilingual_model_path = str(fake_model)
    opus_mt_dir = tmp_path / "opus-mt-pt-en"
    opus_mt_dir.mkdir()
    settings.translation.opus_mt_pt_en_dir = str(opus_mt_dir)


@pytest.mark.asyncio
async def test_pause_portuguese_stream_stops_process_and_sets_paused_status(settings, tmp_path):
    _enable_pt_stream(settings, tmp_path)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    session.status.whisper = "running"  # simulate an active English session
    session._start_portuguese_stream()
    assert session._whisper_pt is not None

    await session.pause_portuguese_stream()

    assert session.status.whisper_pt == "paused"
    assert session._whisper_pt is None
    assert session._consume_task_pt is None
    # The main English session must be completely untouched.
    assert session.status.whisper == "running"


@pytest.mark.asyncio
async def test_pause_portuguese_stream_is_a_noop_when_not_running(settings, tmp_path):
    _enable_pt_stream(settings, tmp_path)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    assert session._whisper_pt is None

    await session.pause_portuguese_stream()  # must not raise

    assert session._whisper_pt is None


@pytest.mark.asyncio
async def test_resume_portuguese_stream_restarts_after_pause(settings, tmp_path):
    _enable_pt_stream(settings, tmp_path)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    session.status.whisper = "running"
    session._start_portuguese_stream()
    await session.pause_portuguese_stream()
    assert session.status.whisper_pt == "paused"

    session.resume_portuguese_stream()

    assert session.status.whisper_pt == "starting"
    assert session._whisper_pt is not None
    session._consume_task_pt.cancel()


def test_resume_portuguese_stream_is_a_noop_when_no_active_session(settings, tmp_path):
    _enable_pt_stream(settings, tmp_path)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    assert session.status.whisper == "stopped"  # no active session

    session.resume_portuguese_stream()

    assert session._whisper_pt is None
    assert session.status.whisper_pt == "disabled"  # untouched, never started


@pytest.mark.asyncio
async def test_resume_portuguese_stream_is_a_noop_when_already_running(settings, tmp_path):
    _enable_pt_stream(settings, tmp_path)
    session = _make_session(settings, translate_pt_en_fn=AsyncMock())
    session.status.whisper = "running"
    session._start_portuguese_stream()
    first_instance = session._whisper_pt

    session.resume_portuguese_stream()

    assert session._whisper_pt is first_instance  # unchanged, not restarted
    session._consume_task_pt.cancel()
