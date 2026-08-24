"""GET /api/health -- section 25.

Returns 200 with per-component status when everything required is
reachable, and 503 when a required component (whisper binary/model, or
the app itself) is missing. Ollama being down is reported but does not
507 the whole app, since transcription can continue without it.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from meeting_copilot.audio.whisper_process import validate_whisper_setup
from meeting_copilot.llm.ollama_client import check_ollama_health

router = APIRouter()


@router.get("/api/health")
async def health(request: Request, response: Response) -> dict[str, Any]:
    state = request.app.state.copilot
    settings = state.settings

    whisper_binary_ok = settings.whisper.binary_path_expanded.exists()
    whisper_model_ok = settings.whisper.model_path_expanded.exists()

    ollama_ok = await check_ollama_health(settings.ollama)

    components = {
        "application": "ok",
        "ollama": "ok" if ollama_ok else "unavailable",
        "model": settings.ollama.model,
        "whisper_binary": "ok" if whisper_binary_ok else "missing",
        "whisper_model": "ok" if whisper_model_ok else "missing",
        "microphone_permission": "unknown",
    }

    required_ok = whisper_binary_ok and whisper_model_ok
    response.status_code = 200 if required_ok else 503

    return {
        "status": "ok" if required_ok else "degraded",
        "components": components,
        "privacy": {
            "external_network_allowed": settings.privacy.allow_external_network,
            "audio_persistence": settings.privacy.persist_audio,
            "transcript_persistence": settings.privacy.persist_transcript,
        },
    }
