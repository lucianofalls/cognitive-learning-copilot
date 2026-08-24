"""Single-process application state.

This is a local, single-user app -- there is intentionally no per-request
session lookup, database, or auth. One AppState instance lives on
`app.state.copilot` for the lifetime of the FastAPI process and is shared
by every route module. See docs/DECISIONS.md for why this was chosen over
a dependency-injection framework.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from meeting_copilot.config import REPO_ROOT, Settings, load_glossary, load_profile
from meeting_copilot.context.opus_mt import translate_pt_to_en
from meeting_copilot.context.spaced_repetition import LearningItemStore
from meeting_copilot.logging_config import log_event
from meeting_copilot.services.coach_service import CoachService
from meeting_copilot.services.language_coach_service import LanguageCoachService
from meeting_copilot.services.learning_service import make_summarize_fn, make_translate_fn
from meeting_copilot.services.session_service import SessionService

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Tracks connected WebSocket clients and fans out JSON events to all of them."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event_type: str, payload: dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False)
        dead: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        for connection in connections:
            try:
                await connection.send_text(message)
            except Exception:  # noqa: BLE001 - a closed socket should not break the loop
                dead.append(connection)
        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)


class AppState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.connections = ConnectionManager()
        self.profile: dict[str, Any] = load_profile()
        self.glossary: dict[str, Any] = load_glossary()
        self.feedback: list[dict[str, Any]] = []

        translate_fn = (
            make_translate_fn(
                settings.ollama,
                lambda: self.glossary,
                settings.translation.engine,
                settings.translation.model,
                settings.translation,
            )
            if settings.translation.enabled
            else None
        )
        summarize_fn = make_summarize_fn(settings.ollama) if settings.summarization.enabled else None

        # Reverse direction (Portuguese speech -> English), for the
        # continuous whisper_pt stream (services/session_service.py). Same
        # opus_mt engine the EN->PT-BR path can use, just the other model
        # directory -- see context/opus_mt.py. Gated by translation.enabled,
        # same master switch as translate_fn above; the more specific
        # whisper.enable_portuguese_stream toggle is checked in
        # SessionService itself (it also needs the model files to exist).
        translate_pt_en_fn = (
            (lambda text: translate_pt_to_en(text, settings.translation.opus_mt_pt_en_dir_expanded))
            if settings.translation.enabled
            else None
        )
        self.session = SessionService(
            settings,
            broadcast=self.connections.broadcast,
            translate_fn=translate_fn,
            translate_pt_en_fn=translate_pt_en_fn,
            summarize_fn=summarize_fn,
            log_dir=REPO_ROOT / "data" / "sessions",
        )
        self.coach = CoachService(settings.ollama)
        self.language_coach = LanguageCoachService(settings.ollama)
        # Gated the same way as SessionService's SessionLogWriter (see
        # services/session_service.py): only constructed when
        # privacy.persist_learning_notes is true, since a learning item's
        # context_sentence holds real English transcript content. `None`
        # here means the Language Coach API routes must treat spaced
        # repetition as unavailable and say so, not silently no-op.
        self.learning_items = (
            LearningItemStore(REPO_ROOT / "data" / "learning_items")
            if settings.privacy.persist_learning_notes
            else None
        )

    def reload_profile(self) -> None:
        self.profile = load_profile()
        log_event(logger, "app_state", "profile_reloaded")

    def reload_glossary(self) -> None:
        self.glossary = load_glossary()
        log_event(logger, "app_state", "glossary_reloaded")
