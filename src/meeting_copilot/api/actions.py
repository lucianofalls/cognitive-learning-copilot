"""POST /api/actions/* -- the seven coach actions from section 13.

Every route here does the same three things: read `idea_pt` (optional)
from the body, ask CoachService to run the matching action, and return a
MeetingCoachResponse. Kept as separate routes (rather than one
/api/actions/{action}) to match the fixed action list in section 20 and
keep the OpenAPI docs self-explanatory.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError

router = APIRouter()


class ActionRequest(BaseModel):
    idea_pt: str = ""


async def _run(request: Request, action: str, body: ActionRequest) -> dict[str, Any]:
    state = request.app.state.copilot
    # Signals the background translation/summary loop (SessionService.
    # _learning_loop) to back off from starting a new Ollama call while
    # this one is in flight -- Ollama on this local setup only processes
    # one request at a time, so without this an on-demand button click
    # can queue behind a periodic refresh with no indication why. A
    # counter (not a bool) because the UI allows firing multiple coach
    # actions concurrently.
    state.session.coach_busy_count += 1
    try:
        result, processing_load_signal = await state.coach.run_action(
            action,  # type: ignore[arg-type]
            state.session,
            state.profile,
            state.glossary,
            user_idea_pt=body.idea_pt,
        )
    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="O modelo local não está disponível. A transcrição pode continuar, mas as sugestões estão pausadas.",
        ) from exc
    except OllamaInvalidResponseError as exc:
        raise HTTPException(status_code=502, detail=f"Resposta do modelo inválida: {exc}") from exc
    finally:
        state.session.coach_busy_count -= 1
    payload = result.model_dump()
    # None when there isn't enough evidence to name a dominant effort --
    # frontend hides the badge entirely in that case rather than showing a
    # placeholder (see web/app.js's renderCardContent).
    payload["processing_load"] = (
        {"dominant_effort": processing_load_signal.dominant_effort, "confidence": processing_load_signal.confidence}
        if processing_load_signal.dominant_effort
        else None
    )
    return payload


@router.post("/api/actions/explain-context")
async def explain_context(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "explain_context", body)


@router.post("/api/actions/suggest-answer")
async def suggest_answer(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "suggest_answer", body)


@router.post("/api/actions/suggest-question")
async def suggest_question(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "suggest_question", body)


@router.post("/api/actions/disagree-politely")
async def disagree_politely(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "disagree_politely", body)


@router.post("/api/actions/request-clarification")
async def request_clarification(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "request_clarification", body)


@router.post("/api/actions/confirm-understanding")
async def confirm_understanding(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "confirm_understanding", body)


@router.post("/api/actions/explain-english")
async def explain_english(request: Request, body: ActionRequest = ActionRequest()) -> dict[str, Any]:
    return await _run(request, "explain_english", body)
