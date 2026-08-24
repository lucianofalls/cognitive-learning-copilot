"""Owns the lifecycle of one meeting session (state, not transport).

A single SessionService instance lives for the lifetime of the FastAPI
process (single-user local app, so no per-request session lookup is
needed). It wires the whisper subprocess, the deduplicator, the rolling
buffer, and the summary/translation managers together, and exposes a
broadcast hook the WebSocket route uses to push events to the browser.

This module stays Ollama-agnostic by design: the actual translation/
summarization calls are injected as callables (`translate_fn`,
`summarize_fn`), built elsewhere (services/learning_service.py) where
OllamaSettings is available. Same reasoning as SummaryManager's own
injected refresh_fn.

Two different refresh strategies live side by side here, on purpose:
- Summary refresh is periodic (`_learning_loop`, every
  `_LEARNING_LOOP_POLL_SECONDS`) -- a summary needs accumulated content
  to be useful, so batching is inherent to what it's for.
- Translation refresh is event-driven (`_maybe_refresh_translation`,
  called from `_handle_transcript_text` after every new segment) -- see
  that method's docstring for why batching was removed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from meeting_copilot.audio.deduplicator import Deduplicator
from meeting_copilot.audio.whisper_process import WhisperProcessManager
from meeting_copilot.config import Settings
from meeting_copilot.context.memory_manager import MemoryManager
from meeting_copilot.context.noticing_detector import find_noticeable_phrase
from meeting_copilot.context.rolling_buffer import RollingTranscriptBuffer
from meeting_copilot.context.summary_manager import SummaryManager
from meeting_copilot.context.translation_manager import TranslationManager
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError
from meeting_copilot.logging_config import log_event
from meeting_copilot.models import MeetingConfig, SessionStatus, TranscriptSegment
from meeting_copilot.persistence.session_log import SessionLogWriter

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict[str, Any]], Awaitable[None]]
TranslateFn = Callable[[str], Awaitable[str]]
SummarizeFn = Callable[[Any, str], Awaitable[Any]]

# How often the background loop checks whether a summary refresh is due.
# Independent of the refresh cadence itself (summarization.interval_seconds),
# which is what actually gates whether a refresh fires on a given tick.
# Translation isn't on this loop -- see _maybe_refresh_translation.
_LEARNING_LOOP_POLL_SECONDS = 5


class SessionService:
    def __init__(
        self,
        settings: Settings,
        broadcast: BroadcastFn | None = None,
        translate_fn: TranslateFn | None = None,
        translate_pt_en_fn: TranslateFn | None = None,
        summarize_fn: SummarizeFn | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.settings = settings
        self._broadcast = broadcast or (lambda event, payload: asyncio.sleep(0))
        self._translate_fn = translate_fn
        # PT->EN, for the reverse continuous stream below -- independent of
        # translate_fn (EN->PT-BR). See _handle_transcript_text_pt.
        self._translate_pt_en_fn = translate_pt_en_fn
        self._summarize_fn = summarize_fn
        self._log_dir = log_dir

        self.status = SessionStatus()
        self.meeting_config = MeetingConfig()
        self.rolling_buffer = RollingTranscriptBuffer(
            window_seconds=settings.whisper.rolling_window_seconds
        )
        # Reverse pipeline's own rolling buffer (the user's PT speech,
        # being translated to English) -- feeds ProcessingLoadDetector
        # (context/processing_load_detector.py) alongside the forward
        # buffer above. The real-time processing difficulties this
        # detector watches for span both understanding English (the
        # forward buffer) and producing it (reflected here even when
        # what's spoken is Portuguese words), so the detector needs
        # segments from both directions -- see
        # recent_segments_for_processing_load below.
        self.rolling_buffer_pt = RollingTranscriptBuffer(
            window_seconds=settings.whisper.rolling_window_seconds
        )
        self.summary_manager = SummaryManager(
            interval_seconds=settings.summarization.interval_seconds,
            max_summary_characters=settings.summarization.max_summary_characters,
        )
        self.translation_manager = TranslationManager()
        # Separate instance, own pending-text buffer -- the PT->EN stream is
        # completely independent of the EN->PT-BR one (different source
        # language, different whisper process, different translate_fn).
        self.translation_manager_pt = TranslationManager()
        self.memory_manager = MemoryManager()
        self._deduplicator = Deduplicator()
        self._deduplicator_pt = Deduplicator()
        self._whisper: WhisperProcessManager | None = None
        self._consume_task: asyncio.Task | None = None
        # Second, independent continuous whisper-stream process (multilingual
        # model, -l pt) -- see start()/stop(). Kept independent on purpose
        # (whisper.cpp and Ollama failures must never take each other
        # down): this stream's lifecycle and status (status.whisper_pt)
        # never touch the main one (status.whisper).
        self._whisper_pt: WhisperProcessManager | None = None
        self._consume_task_pt: asyncio.Task | None = None
        self._learning_task: asyncio.Task | None = None
        self._log_writer: SessionLogWriter | None = None
        self._last_segment_at: datetime | None = None
        # Cooldown state for the proactive noticing flag (theory #2) --
        # see _matched_noticeable_phrase.
        self._last_noticing_broadcast_at: datetime | None = None
        # Ollama serializes requests *within one loaded model's process*
        # (OLLAMA_NUM_PARALLEL=1), but different models each get their own
        # llama-server process and genuinely run concurrently -- verified
        # empirically: a llama3.2:1b call and a llama3.2:3b call fired at
        # the same instant finished independently, one well before the
        # other. So this only needs to gate work that shares a model with
        # the coach actions (summary always does; translation only does
        # if `translation.model` is unset -- see `_learning_loop`).
        # Without gating the shared-model case, a periodic refresh firing
        # right when the user clicks a coach action button would queue
        # behind it and the button could take upwards of two minutes to
        # respond, with no indication why. api/actions.py increments this
        # for the duration of each on-demand action and decrements on
        # completion. A counter, not a bool, because the UI now
        # allows firing multiple coach actions concurrently (each gets
        # its own response card) -- a bool would get reset to "not busy"
        # by whichever concurrent action finishes first, even while
        # others are still in flight.
        self.coach_busy_count = 0
        # Guards _maybe_refresh_translation against firing two overlapping
        # translation calls when a new transcript segment arrives while the
        # previous one's call is still in flight.
        self._translation_refresh_lock = asyncio.Lock()
        # Same guard, independent lock, for the PT->EN stream.
        self._translation_pt_refresh_lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------

    async def start(self) -> None:
        if self.status.whisper in ("starting", "running"):
            return
        self.status.session_id = _new_session_id()
        self.status.started_at = datetime.now(timezone.utc).astimezone()
        self.status.whisper = "starting"

        if self._translate_fn is not None and self.settings.translation.engine == "argos":
            # See argos_translate.wait_ready -- avoids the first live
            # translation of the session paying the ~6-10s cold-load cost
            # if the app-startup warm-up (main.py::_warm_argos) hasn't
            # finished yet. Best-effort: a timeout just means we proceed
            # and pay the cold-load cost anyway, same as before this existed.
            from meeting_copilot.context.argos_translate import wait_ready

            became_ready = await wait_ready()
            if not became_ready:
                log_event(logger, "session_service", "argos_warmup_wait_timed_out", level=logging.WARNING)

        persist = self._log_dir is not None and self.settings.privacy.persist_learning_notes
        self.status.learning_persisted = persist
        self._log_writer = SessionLogWriter(self._log_dir, self.status.session_id) if persist else None
        self._last_segment_at = None
        self._last_noticing_broadcast_at = None

        await self._broadcast("session.status", self.status.model_dump(mode="json"))

        self._whisper = WhisperProcessManager(
            self.settings.whisper,
            on_status_change=self._on_whisper_status_change_sync,
        )
        self._consume_task = asyncio.create_task(self._consume_transcript())
        # Translation is event-driven now (_maybe_refresh_translation, fired
        # from _handle_transcript_text) -- this loop only owns the summary.
        if self._summarize_fn:
            self._learning_task = asyncio.create_task(self._learning_loop())

        self._start_portuguese_stream()

        log_event(
            logger,
            "session_service",
            "session_started",
            session_id=self.status.session_id,
            learning_persisted=persist,
        )

    def _start_portuguese_stream(self) -> None:
        """Starts the second, continuous whisper-stream process (multilingual
        model, -l pt) that recognizes Portuguese speech live, the same way
        the main whisper-stream recognizes English -- see WhisperSettings.
        enable_portuguese_stream's docstring for why this is a genuinely
        separate process/model rather than reusing the main one.

        Best-effort and independent of the main pipeline: if disabled, or
        the multilingual model hasn't been downloaded, this just leaves
        status.whisper_pt as "disabled"/"error" and returns -- it must
        never prevent or degrade the main English session from starting.
        """
        if not self.settings.whisper.enable_portuguese_stream or self._translate_pt_en_fn is None:
            self.status.whisper_pt = "disabled"
            return
        pt_model_path = self.settings.whisper.multilingual_model_path_expanded
        if not pt_model_path.exists():
            log_event(
                logger, "session_service", "portuguese_stream_model_missing",
                level=logging.WARNING, model_path=str(pt_model_path),
            )
            self.status.whisper_pt = "disabled"
            return
        opus_mt_pt_en_dir = self.settings.translation.opus_mt_pt_en_dir_expanded
        if not opus_mt_pt_en_dir.exists():
            log_event(
                logger, "session_service", "portuguese_stream_translation_model_missing",
                level=logging.WARNING, model_dir=str(opus_mt_pt_en_dir),
            )
            self.status.whisper_pt = "disabled"
            return

        pt_whisper_settings = self.settings.whisper.model_copy(
            update={"model_path": self.settings.whisper.multilingual_model_path, "language": "pt"}
        )
        self.status.whisper_pt = "starting"
        self._whisper_pt = WhisperProcessManager(
            pt_whisper_settings,
            on_status_change=self._on_whisper_pt_status_change_sync,
        )
        self._consume_task_pt = asyncio.create_task(self._consume_transcript_pt())

    async def pause_portuguese_stream(self) -> None:
        """Stops the second whisper-stream process specifically, leaving
        the main English session (status.whisper) completely untouched --
        used when the "FALAR EM PORTUGUÊS" panel is minimized (web/app.js)
        to actually save CPU while minimized, not just hide the UI.
        A no-op if it isn't currently running (already paused, disabled,
        or no session).
        """
        if self._whisper_pt is None:
            return
        await self._whisper_pt.stop()
        self._whisper_pt = None
        if self._consume_task_pt is not None:
            self._consume_task_pt.cancel()
            self._consume_task_pt = None
        self.status.whisper_pt = "paused"
        await self._broadcast("session.status", self.status.model_dump(mode="json"))
        log_event(logger, "session_service", "portuguese_stream_paused")

    def resume_portuguese_stream(self) -> None:
        """Restarts the second whisper-stream process after pause_
        portuguese_stream -- used when the panel is maximized again.
        A no-op if there's no active English session to attach to (the
        whole session must be running first), or if it's already
        running/permanently disabled -- see _start_portuguese_stream,
        which this reuses so both code paths agree on what "available"
        means.
        """
        if self.status.whisper not in ("starting", "running"):
            return
        if self._whisper_pt is not None:
            return
        self._start_portuguese_stream()
        log_event(logger, "session_service", "portuguese_stream_resumed")

    async def stop(self) -> None:
        if self._whisper is not None:
            await self._whisper.stop()
        if self._consume_task is not None:
            self._consume_task.cancel()
            self._consume_task = None
        if self._learning_task is not None:
            self._learning_task.cancel()
            self._learning_task = None
        if self._whisper_pt is not None:
            await self._whisper_pt.stop()
            self._whisper_pt = None
        if self._consume_task_pt is not None:
            self._consume_task_pt.cancel()
            self._consume_task_pt = None
        self.status.whisper = "stopped"
        if self.status.whisper_pt != "disabled":
            self.status.whisper_pt = "stopped"
        await self._broadcast("session.status", self.status.model_dump(mode="json"))
        log_event(logger, "session_service", "session_stopped", session_id=self.status.session_id)

    def delete_session(self) -> None:
        """Section 4: 'Apagar sessão' -- wipe all in-memory session state."""
        self.rolling_buffer.clear()
        self.rolling_buffer_pt.clear()
        self.summary_manager = SummaryManager(
            interval_seconds=self.settings.summarization.interval_seconds,
            max_summary_characters=self.settings.summarization.max_summary_characters,
        )
        self.translation_manager = TranslationManager()
        self.memory_manager.clear()
        if self._log_writer is not None:
            self._log_writer.path.unlink(missing_ok=True)
        self.status = SessionStatus()
        self._log_writer = None
        self._last_segment_at = None
        self._last_noticing_broadcast_at = None
        log_event(logger, "session_service", "session_deleted")

    # -- transcript ----------------------------------------------------

    def _on_whisper_status_change_sync(self, status: str) -> None:
        self.status.whisper = status  # type: ignore[assignment]
        asyncio.create_task(self._broadcast("session.status", self.status.model_dump(mode="json")))

    async def _consume_transcript(self) -> None:
        assert self._whisper is not None
        try:
            async for text in self._whisper.iter_transcript_lines():
                await self._handle_transcript_text(text)
        except Exception as exc:  # noqa: BLE001 - surface to UI, keep session alive
            log_event(
                logger,
                "session_service",
                "transcript_consumption_error",
                level=logging.ERROR,
                error=str(exc),
            )
            self.status.whisper = "error"
            await self._broadcast("session.status", self.status.model_dump(mode="json"))

    async def _handle_transcript_text(self, text: str) -> None:
        pipeline_start = time.monotonic()
        if self._deduplicator.is_exact_duplicate(text):
            return
        trimmed = self._deduplicator.trim_overlap(text)
        if not trimmed:
            return

        segment = TranscriptSegment(text=trimmed, normalized_text=trimmed.lower(), stable=True)
        self.rolling_buffer.add(segment)
        self.summary_manager.add_stable_text(trimmed)

        # Gap since the previous segment is the lightweight "speech nuance"
        # signal: a long silence before this chunk usually means hesitation
        # or a topic change, so it's worth flagging in the translated notes
        # rather than silently smoothing it away.
        pause_seconds: float | None = None
        if self._last_segment_at is not None:
            pause_seconds = (segment.created_at - self._last_segment_at).total_seconds()
        self._last_segment_at = segment.created_at
        self.translation_manager.add_stable_text(trimmed, pause_seconds=pause_seconds)
        if self._translate_fn is not None:
            asyncio.create_task(self._maybe_refresh_translation())

        await self._broadcast(
            "transcript.segment",
            {"text": segment.text, "stable": segment.stable, "created_at": segment.created_at.isoformat()},
        )
        log_event(
            logger,
            "session_service",
            "transcript_segment_broadcast",
            # How long dedup + buffering + WS broadcast took, in this
            # process, from receiving the text to the browser push going
            # out. Should be low single-digit ms -- if transcription feels
            # laggy, this confirms whether the delay is here or upstream
            # in whisper-stream itself (see whisper_process.py's own
            # transcript_line_ready/heartbeat logs for that half).
            pipeline_ms=round((time.monotonic() - pipeline_start) * 1000),
            text_length=len(trimmed),
        )

        if self._matches_direct_question(trimmed):
            await self._broadcast(
                "possible_direct_question",
                {"matched_phrase": self._matched_phrase(trimmed), "recent_text": trimmed},
            )

        noticeable = self._matched_noticeable_phrase(trimmed)
        if noticeable:
            await self._broadcast(
                "noticing.flag",
                {"matched_phrase": noticeable, "sentence": trimmed},
            )

    async def _maybe_refresh_translation(self) -> None:
        """Fires a translation refresh right after each new transcript segment.

        Batching (interval_seconds/min_new_characters) made sense when
        translation went through Ollama at 15-25s/call -- translating every
        ~3s transcript segment individually would have meant translation
        permanently trailing behind live speech. Argos Translate replaced
        that (see argos_translate.py's docstring) and calls typically finish
        in well under a second, so nothing is gained by waiting; per-segment
        translation gets PT-BR on screen close to the moment each segment
        is transcribed instead of every ~25s, which is what was actually
        asked for -- see docs/DECISIONS.md, 2026-07-20.

        `_translation_refresh_lock` prevents overlapping calls if a refresh
        is still in flight when the next segment arrives (e.g. Ollama's
        summary call is hogging the shared CPU for a moment): the new text
        just accumulates in TranslationManager's pending buffer and rides
        along on the next refresh, same graceful-degradation behavior the
        old interval/char-count batching had, just opportunistic instead of
        scheduled.
        """
        if self._translation_refresh_lock.locked():
            return
        if self.coach_busy_count > 0 and self._translation_shares_coach_model:
            return
        async with self._translation_refresh_lock:
            await self._refresh_translation()

    async def _refresh_translation(self) -> None:
        assert self._translate_fn is not None
        start = time.monotonic()
        try:
            translated = await self.translation_manager.refresh(self._translate_fn)
        except (OllamaUnavailableError, OllamaInvalidResponseError) as exc:
            log_event(
                logger, "session_service", "translation_refresh_failed",
                level=logging.WARNING, error=str(exc),
            )
            return
        call_ms = round((time.monotonic() - start) * 1000)
        if translated:
            broadcast_start = time.monotonic()
            await self._broadcast("translation.update", {"text_pt": translated})
            broadcast_ms = round((time.monotonic() - broadcast_start) * 1000)
            log_event(
                logger, "session_service", "translation_refreshed",
                call_ms=call_ms, broadcast_ms=broadcast_ms, text_length=len(translated),
            )
            if self._log_writer is not None:
                self._log_writer.write_translation(translated)

    # -- reverse pipeline: Portuguese speech -> English translation -----

    def _on_whisper_pt_status_change_sync(self, status: str) -> None:
        # Deliberately writes status.whisper_pt, never status.whisper --
        # see that field's docstring in models.py.
        self.status.whisper_pt = status  # type: ignore[assignment]
        asyncio.create_task(self._broadcast("session.status", self.status.model_dump(mode="json")))

    async def _consume_transcript_pt(self) -> None:
        assert self._whisper_pt is not None
        try:
            async for text in self._whisper_pt.iter_transcript_lines():
                await self._handle_transcript_text_pt(text)
        except Exception as exc:  # noqa: BLE001 - never take down the English pipeline over this
            log_event(
                logger, "session_service", "transcript_pt_consumption_error",
                level=logging.ERROR, error=str(exc),
            )
            self.status.whisper_pt = "error"
            await self._broadcast("session.status", self.status.model_dump(mode="json"))

    async def _handle_transcript_text_pt(self, text: str) -> None:
        """Mirrors _handle_transcript_text, minus the parts specific to the
        English meeting (summary, direct-question detection only make sense
        for the English pipeline the Meeting Coach is anchored to).
        rolling_buffer_pt is the one exception, added 2026-07-23 for
        ProcessingLoadDetector -- see its assignment in __init__."""
        if self._deduplicator_pt.is_exact_duplicate(text):
            return
        trimmed = self._deduplicator_pt.trim_overlap(text)
        if not trimmed:
            return

        segment = TranscriptSegment(text=trimmed, normalized_text=trimmed.lower(), stable=True)
        self.rolling_buffer_pt.add(segment)
        self.translation_manager_pt.add_stable_text(trimmed)
        if self._translate_pt_en_fn is not None:
            asyncio.create_task(self._maybe_refresh_translation_pt())

        await self._broadcast("transcript_pt.segment", {"text": trimmed})

    def recent_segments_for_processing_load(self) -> list[TranscriptSegment]:
        """Segments from both pipelines, merged and time-sorted, for
        ProcessingLoadDetector.analyze() (context/processing_load_detector.py,
        LANGUAGE_COACH_PEDAGOGY.md theory #15).

        Sorted by created_at because the detector's memory-gap heuristic
        (a long pause between consecutive segments) only means anything
        over a single chronological timeline -- concatenating the two
        buffers unsorted would compare timestamps across two independent
        streams that don't interleave in insertion order.
        """
        combined = self.rolling_buffer.recent_segments() + self.rolling_buffer_pt.recent_segments()
        combined.sort(key=lambda segment: segment.created_at)
        return combined

    async def _maybe_refresh_translation_pt(self) -> None:
        """PT->EN counterpart of _maybe_refresh_translation -- same
        event-driven-per-segment reasoning and same overlap guard, via its
        own independent lock so the two directions never block each other.
        """
        if self._translation_pt_refresh_lock.locked():
            return
        async with self._translation_pt_refresh_lock:
            await self._refresh_translation_pt()

    async def _refresh_translation_pt(self) -> None:
        assert self._translate_pt_en_fn is not None
        start = time.monotonic()
        try:
            translated = await self.translation_manager_pt.refresh(self._translate_pt_en_fn)
        except Exception as exc:  # noqa: BLE001 - never take down the PT stream or the English pipeline over this
            log_event(
                logger, "session_service", "translation_pt_refresh_failed",
                level=logging.WARNING, error=str(exc),
            )
            return
        call_ms = round((time.monotonic() - start) * 1000)
        if translated:
            await self._broadcast("translation_en.update", {"text_en": translated})
            log_event(
                logger, "session_service", "translation_pt_refreshed",
                call_ms=call_ms, text_length=len(translated),
            )

    async def _refresh_summary(self) -> None:
        assert self._summarize_fn is not None
        try:
            await self.summary_manager.refresh(self._summarize_fn)
        except (OllamaUnavailableError, OllamaInvalidResponseError) as exc:
            log_event(
                logger, "session_service", "summary_refresh_failed",
                level=logging.WARNING, error=str(exc),
            )
            return
        await self._broadcast("summary.update", self.summary_manager.summary.model_dump(mode="json"))
        if self._log_writer is not None:
            self._log_writer.write_summary(self.summary_manager.summary)

    @property
    def _translation_shares_coach_model(self) -> bool:
        """True if translation competes with the coach actions for Ollama.

        `translation.engine == "argos"` (the default) doesn't touch
        Ollama at all -- it's a separate local NMT engine, never
        contends. `engine == "ollama"` with `translation.model` empty
        falls back to `ollama.model`, the same process the coach actions
        use, so it genuinely needs to wait its turn; a non-empty,
        distinct model runs as its own llama-server process and doesn't.
        """
        if self.settings.translation.engine != "ollama":
            return False
        model = self.settings.translation.model
        return not model or model == self.settings.ollama.model

    async def _learning_loop(self) -> None:
        """Periodically refresh the meeting summary.

        Best-effort: a failed Ollama call here must never take down the
        session -- whisper keeps transcribing regardless, since
        whisper.cpp and Ollama failures are always handled independently.

        Translation used to be refreshed here too, on the same
        interval_seconds/min_new_characters batching as the summary. It's
        now event-driven instead -- see _maybe_refresh_translation, called
        directly from _handle_transcript_text -- so this loop only owns the
        summary, which still benefits from batching (a summary of one
        3s transcript fragment isn't useful; it needs accumulated content).
        """
        while True:
            await asyncio.sleep(_LEARNING_LOOP_POLL_SECONDS)

            coach_busy = self.coach_busy_count > 0
            # Summary always shares ollama.model with the coach actions
            # (no per-summary model override exists), so it always backs
            # off -- see coach_busy_count's docstring in __init__.
            if self._summarize_fn is not None and self.summary_manager.should_refresh() and not coach_busy:
                await self._refresh_summary()

    def _matches_direct_question(self, text: str) -> bool:
        if not self.settings.automation.detect_direct_questions:
            return False
        return self._matched_phrase(text) is not None

    def _matched_phrase(self, text: str) -> str | None:
        lowered = text.lower()
        for phrase in self.settings.automation.trigger_phrases:
            if phrase.lower() in lowered:
                return phrase
        if text.strip().endswith("?"):
            return "?"
        return None

    def _matched_noticeable_phrase(self, text: str) -> str | None:
        """Proactive half of the Noticing Hypothesis (theory #2) -- gated
        by `automation.detect_noticeable_language` and a cooldown so a
        transcript dense with idioms can't turn the badge into ambient/
        repeated motion (ADHD_NEUROSCIENCE_REFERENCE.md rule #2)."""
        if not self.settings.automation.detect_noticeable_language:
            return None
        now = datetime.now(timezone.utc).astimezone()
        if self._last_noticing_broadcast_at is not None:
            elapsed = (now - self._last_noticing_broadcast_at).total_seconds()
            if elapsed < self.settings.automation.noticing_cooldown_seconds:
                return None
        matched = find_noticeable_phrase(text)
        if matched:
            self._last_noticing_broadcast_at = now
        return matched


def _new_session_id() -> str:
    import uuid

    return f"local-session-{uuid.uuid4().hex[:8]}"
