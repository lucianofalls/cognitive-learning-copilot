"""FastAPI application entrypoint.

Run with `scripts/start.sh`, or directly:

    uvicorn meeting_copilot.main:app --host 127.0.0.1 --port 8000

`server.host` is read from config/settings.yaml but this module refuses
to bind anywhere except loopback addresses (127.0.0.1 / ::1 / localhost)
regardless of what the config says -- see `_assert_loopback_only`. That
is a deliberate hard-coded guardrail, not something meant to be
configurable, per section 4 of the product spec.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from meeting_copilot.api import actions, configuration, health, language_coach, session, translate, websocket
from meeting_copilot.app_state import AppState
from meeting_copilot.config import REPO_ROOT, get_settings
from meeting_copilot.logging_config import configure_logging, log_event

logger = logging.getLogger(__name__)

WEB_DIR = REPO_ROOT / "web"

_ALLOWED_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _assert_loopback_only(host: str) -> None:
    if host not in _ALLOWED_LOOPBACK_HOSTS:
        raise RuntimeError(
            f"Refusing to start: server.host='{host}' is not a loopback address. "
            "This application must never bind to a network-reachable interface. "
            "Set server.host to 127.0.0.1 in config/settings.yaml."
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    _assert_loopback_only(settings.server.host)
    app.state.copilot = AppState(settings)
    if settings.translation.enabled and settings.translation.engine == "argos":
        # Loading the NMT model takes ~6-10s the first time it's used;
        # do that now in the background instead of on the first real
        # translation of a live session. Best-effort -- a failure here
        # just means the first translation call pays the load cost
        # instead, same as if this warm-up didn't exist.
        async def _warm_argos() -> None:
            from meeting_copilot.context.argos_translate import translate_en_to_pt

            try:
                await translate_en_to_pt("ready")
                log_event(logger, "main", "argos_translate_warmed")
            except Exception as exc:  # noqa: BLE001 - best-effort warm-up only
                log_event(logger, "main", "argos_translate_warmup_failed", level=logging.WARNING, error=str(exc))

        asyncio.create_task(_warm_argos())
    log_event(logger, "main", "application_started", host=settings.server.host, port=settings.server.port)
    try:
        yield
    finally:
        await app.state.copilot.session.stop()
        log_event(logger, "main", "application_stopped")


app = FastAPI(title="Local English Meeting Copilot", lifespan=lifespan)

app.include_router(health.router)
app.include_router(session.router)
app.include_router(actions.router)
app.include_router(language_coach.router)
app.include_router(translate.router)
app.include_router(configuration.router)
app.include_router(websocket.router)

if (WEB_DIR / "styles.css").exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


def run() -> None:
    """Entry point used by `python -m meeting_copilot.main` and scripts/start.sh."""
    import uvicorn

    settings = get_settings()
    _assert_loopback_only(settings.server.host)
    uvicorn.run(
        "meeting_copilot.main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
