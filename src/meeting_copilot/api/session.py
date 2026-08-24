"""Session lifecycle + meeting/profile/glossary configuration endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from meeting_copilot.audio.whisper_process import list_capture_devices
from meeting_copilot.config import CONFIG_DIR, save_glossary
from meeting_copilot.models import MeetingConfig

router = APIRouter()


@router.post("/api/session/start")
async def start_session(request: Request) -> dict[str, Any]:
    state = request.app.state.copilot
    try:
        await state.session.start()
    except Exception as exc:  # noqa: BLE001 - convert to a clean HTTP error
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return state.session.status.model_dump(mode="json")


@router.post("/api/session/stop")
async def stop_session(request: Request) -> dict[str, Any]:
    state = request.app.state.copilot
    await state.session.stop()
    return state.session.status.model_dump(mode="json")


@router.post("/api/session/delete")
async def delete_session(request: Request) -> dict[str, str]:
    state = request.app.state.copilot
    await state.session.stop()
    state.session.delete_session()
    return {"status": "deleted"}


@router.post("/api/session/pause-pt-stream")
async def pause_pt_stream(request: Request) -> dict[str, Any]:
    """Called when the "FALAR EM PORTUGUÊS" panel is minimized (web/app.js)
    -- stops that one whisper-stream process to save CPU, leaves the main
    English session untouched. See SessionService.pause_portuguese_stream.
    """
    state = request.app.state.copilot
    await state.session.pause_portuguese_stream()
    return state.session.status.model_dump(mode="json")


@router.post("/api/session/resume-pt-stream")
async def resume_pt_stream(request: Request) -> dict[str, Any]:
    """Called when the "FALAR EM PORTUGUÊS" panel is maximized again."""
    state = request.app.state.copilot
    state.session.resume_portuguese_stream()
    return state.session.status.model_dump(mode="json")


@router.get("/api/session/state")
async def session_state(request: Request) -> dict[str, Any]:
    state = request.app.state.copilot
    session = state.session
    return {
        "status": session.status.model_dump(mode="json"),
        "meeting": session.meeting_config.model_dump(),
        "summary": session.summary_manager.summary.model_dump(),
        "recent_transcript": session.rolling_buffer.recent_text(),
        "approved_memory": [m.model_dump(mode="json") for m in session.memory_manager.list_approved()],
    }


@router.get("/api/config")
async def get_config(request: Request) -> dict[str, Any]:
    state = request.app.state.copilot
    return state.settings.model_dump()


@router.put("/api/config/meeting")
async def put_meeting_config(request: Request, meeting: MeetingConfig) -> dict[str, Any]:
    state = request.app.state.copilot
    state.session.meeting_config = meeting
    return meeting.model_dump()


@router.get("/api/audio/devices")
async def get_audio_devices(request: Request) -> dict[str, Any]:
    state = request.app.state.copilot
    devices = await list_capture_devices(state.settings.whisper)
    return {"devices": devices, "current": state.settings.whisper.capture_device}


@router.put("/api/config/audio-device")
async def put_audio_device(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    """Body: {"capture_device": 1}.

    In-memory only for this run of the app -- not written to
    config/settings.yaml (this project's rule: never modify a user's
    config files without a backup, so a REST call never does it
    silently). Stop the session first: the running whisper-stream
    process already launched with the old device, so changing this
    mid-session wouldn't do anything but would look like it did.
    """
    state = request.app.state.copilot
    if state.session.status.whisper in ("starting", "running"):
        raise HTTPException(
            status_code=409,
            detail="Pare a sessão atual antes de trocar o dispositivo de áudio.",
        )
    device = body.get("capture_device")
    if not isinstance(device, int):
        raise HTTPException(status_code=400, detail="'capture_device' deve ser um inteiro")
    state.settings.whisper.capture_device = device
    return {"capture_device": state.settings.whisper.capture_device}


@router.get("/api/config/profile")
async def get_profile(request: Request) -> dict[str, Any]:
    return request.app.state.copilot.profile


@router.put("/api/config/profile")
async def put_profile(request: Request, profile: dict[str, Any]) -> dict[str, Any]:
    state = request.app.state.copilot
    state.profile = profile
    return state.profile


@router.get("/api/glossary")
async def get_glossary(request: Request) -> dict[str, Any]:
    return request.app.state.copilot.glossary


@router.post("/api/glossary")
async def add_glossary_term(request: Request, term: dict[str, Any]) -> dict[str, Any]:
    """Body: {"term": "SLO", "preserve": true, "expansion": "Service Level Objective"}"""
    state = request.app.state.copilot
    name = term.get("term")
    if not name:
        raise HTTPException(status_code=400, detail="'term' is required")
    entry = {k: v for k, v in term.items() if k != "term"}
    state.glossary.setdefault("terms", {})[name] = entry
    save_glossary(state.glossary, CONFIG_DIR / "glossary.yaml")
    return state.glossary


@router.delete("/api/glossary/{term}")
async def delete_glossary_term(request: Request, term: str) -> dict[str, Any]:
    state = request.app.state.copilot
    terms = state.glossary.get("terms", {})
    if term in terms:
        del terms[term]
        save_glossary(state.glossary, CONFIG_DIR / "glossary.yaml")
    return state.glossary
