"""POST /api/language-coach/* -- Language Coach Phase 1+2+3a.

Same shape as api/actions.py: thin routes, no business logic here.
`_call_coach` mirrors api/actions.py's `_run` helper -- same
coach_busy_count gating and Ollama-error-to-HTTPException translation,
factored out for the same reason: ask/scenario/pronunciation-check all
need it identically, and actions.py already established that this
codebase extracts that duplication rather than repeating it per route.

Phase 1 (ask/scenario) and Phase 3a's feedback step (pronunciation-check)
call Ollama, so those routes go through `_call_coach` -- Language Coach
reuses ollama.model, so it genuinely contends with the 7 meeting-coach
actions for the same llama-server process (see
services/language_coach_service.py's module docstring). Phase 2
(speak/learning-items/review-queue/review-result) never touches
Ollama -- `say` and the local JSON store are independent resources --
so none of those routes go through it.

pronunciation-check's whisper-cli step (context/pronunciation.py) is a
one-shot subprocess, not Ollama, so it isn't part of coach_busy_count
either -- see docs/LANGUAGE_COACH_ARCHITECTURE.md section 3c for why
that's expected to be safe to run even during a live meeting session
(a few seconds of audio finishes in well under a second, a tiny
fraction of what whisper-stream is continuously doing) -- flagged
there as needing a real measurement before relying on it in practice,
not assumed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from meeting_copilot.context.processing_load_detector import ProcessingLoadSignal
from meeting_copilot.context.pronunciation import (
    PronunciationCheckError,
    match_quality_for,
    transcribe_attempt,
)
from meeting_copilot.context.pronunciation_guide import respell_text
from meeting_copilot.context.spaced_repetition import LearningItem
from meeting_copilot.context.tts import SpeechSynthesisError, synthesize_speech
from meeting_copilot.llm.ollama_client import OllamaInvalidResponseError, OllamaUnavailableError
from meeting_copilot.llm.schemas import PronunciationFeedback, PronunciationGuide
from meeting_copilot.services.session_service import SessionService


def _with_processing_load(payload: dict[str, Any], signal: ProcessingLoadSignal) -> dict[str, Any]:
    """Merges the heuristic processing-load signal into a response dict the
    same way api/actions.py does -- kept out of the Pydantic response
    schemas themselves (see coach_service.py's run_action for why)."""
    payload["processing_load"] = (
        {"dominant_effort": signal.dominant_effort, "confidence": signal.confidence}
        if signal.dominant_effort
        else None
    )
    return payload

router = APIRouter()

_LEARNING_ITEMS_DISABLED_DETAIL = (
    "A fila de revisão está desativada porque privacy.persist_learning_notes "
    "é false em config/settings.yaml -- itens de repetição espaçada guardam a "
    "frase original em inglês, então seguem a mesma permissão das notas de "
    "sessão."
)

_T = TypeVar("_T")


async def _call_coach(session: SessionService, call: Callable[[], Awaitable[_T]]) -> _T:
    session.coach_busy_count += 1
    try:
        return await call()
    except OllamaUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="O modelo local não está disponível. Tente novamente em instantes.",
        ) from exc
    except OllamaInvalidResponseError as exc:
        raise HTTPException(status_code=502, detail=f"Resposta do modelo inválida: {exc}") from exc
    finally:
        session.coach_busy_count -= 1


class AskRequest(BaseModel):
    question: str = ""
    source_sentence_en: str = ""


class ScenarioRequest(BaseModel):
    target_pattern: str


class PronunciationGuideRequest(BaseModel):
    source_text_en: str


class SpeakRequest(BaseModel):
    text: str
    # "en" (default, voice "Daniel") or "pt" (voice "Luciana", pt_BR --
    # confirmed installed via `say -v '?'`). Added 2026-07-22 so the
    # bidirectional idea-box (api/translate.py) can play back results in
    # whichever language they're actually in, not always English.
    lang: str = "en"


class AddLearningItemRequest(BaseModel):
    content_en: str
    context_sentence: str = ""
    kind: str = "chunk"


class ReviewResultRequest(BaseModel):
    item_id: str
    recalled: bool


@router.post("/api/language-coach/ask")
async def ask(request: Request, body: AskRequest) -> dict[str, Any]:
    if not body.question and not body.source_sentence_en:
        raise HTTPException(status_code=422, detail="Informe uma pergunta ou uma frase de contexto.")

    state = request.app.state.copilot
    result, processing_load_signal = await _call_coach(
        state.session,
        lambda: state.language_coach.explain(
            state.profile,
            state.session,
            question=body.question,
            source_sentence_en=body.source_sentence_en,
        ),
    )
    return _with_processing_load(result.model_dump(), processing_load_signal)


_STRESS_NOTE_PT = "Vogal com acento (á, é, í, ó, ê...) = sílaba tônica (a mais forte)."


@router.post("/api/language-coach/pronunciation-guide")
async def pronunciation_guide(request: Request, body: PronunciationGuideRequest) -> PronunciationGuide:
    """"How does this actually sound" -- a Portuguese-orthography phonetic
    respelling for any English text, requested proactively (no recording,
    unlike pronunciation-check). Deterministic CMU-dictionary lookup
    (context/pronunciation_guide.py), not an LLM call -- see
    PronunciationGuide's docstring for why. No Ollama involved, so this
    doesn't go through `_call_coach`/coach_busy_count, same as /speak.
    """
    text = body.source_text_en.strip()
    if not text:
        raise HTTPException(status_code=422, detail="source_text_en não pode ser vazio.")
    return PronunciationGuide(
        source_text_en=text,
        phonetic_respelling_pt=respell_text(text),
        stress_note_pt=_STRESS_NOTE_PT,
    )


_VOICE_BY_LANG = {"en": "Daniel", "pt": "Luciana"}


@router.post("/api/language-coach/speak")
async def speak(request: Request, body: SpeakRequest) -> Response:
    """Phase 2 "Ouvir" affordance -- synthesizes `body.text` via macOS `say`.

    Text-only, doesn't touch Ollama, so it doesn't go through `_call_coach`.
    """
    voice = _VOICE_BY_LANG.get(body.lang, _VOICE_BY_LANG["en"])
    try:
        audio_bytes = await synthesize_speech(body.text, voice=voice)
    except SpeechSynthesisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=audio_bytes, media_type="audio/wav")


@router.post("/api/language-coach/learning-items")
async def add_learning_item(request: Request, body: AddLearningItemRequest) -> LearningItem:
    """Phase 2 "mark for review" -- adds a chunk to the spaced-repetition store.

    Gated by privacy.persist_learning_notes (see app_state.py) because
    `context_sentence` holds a real, verbatim English sentence from the
    meeting -- exactly the content this project never persists by
    default.
    """
    store = request.app.state.copilot.learning_items
    if store is None:
        raise HTTPException(status_code=503, detail=_LEARNING_ITEMS_DISABLED_DETAIL)
    if not body.content_en.strip():
        raise HTTPException(status_code=422, detail="content_en não pode ser vazio.")
    return store.add(body.content_en, body.context_sentence, body.kind)


@router.get("/api/language-coach/review-queue")
async def review_queue(request: Request) -> dict[str, Any]:
    store = request.app.state.copilot.learning_items
    if store is None:
        return {"enabled": False, "items": []}
    return {"enabled": True, "items": [item.model_dump(mode="json") for item in store.due()]}


@router.post("/api/language-coach/review-result")
async def review_result(request: Request, body: ReviewResultRequest) -> LearningItem:
    store = request.app.state.copilot.learning_items
    if store is None:
        raise HTTPException(status_code=503, detail=_LEARNING_ITEMS_DISABLED_DETAIL)
    updated = store.record_result(body.item_id, body.recalled)
    if updated is None:
        raise HTTPException(status_code=404, detail="Item de revisão não encontrado.")
    return updated


@router.post("/api/language-coach/scenario")
async def scenario(request: Request, body: ScenarioRequest) -> dict[str, Any]:
    state = request.app.state.copilot
    result, processing_load_signal = await _call_coach(
        state.session, lambda: state.language_coach.scenario(state.profile, state.session, body.target_pattern)
    )
    return _with_processing_load(result.model_dump(), processing_load_signal)


@router.post("/api/language-coach/pronunciation-check")
async def pronunciation_check(
    request: Request,
    target_text: str = Form(...),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    """Phase 3a: browser-recorded practice attempt -> whisper-cli -> LLM feedback.

    `audio` must already be WAV (PCM) -- whisper-cli's supported input
    formats are flac/mp3/ogg/wav (confirmed via `--help`), not the
    webm/opus or mp4/aac a browser's MediaRecorder produces by default,
    so the frontend re-encodes to WAV client-side before uploading
    (see web/language_coach.js's `encodeWav`) rather than adding a
    server-side transcoding dependency for this.
    """
    if not target_text.strip():
        raise HTTPException(status_code=422, detail="target_text não pode ser vazio.")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Áudio vazio.")

    state = request.app.state.copilot
    try:
        transcription = await transcribe_attempt(audio_bytes, state.settings.whisper)
    except PronunciationCheckError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    quality = match_quality_for(transcription.heard_text, target_text)

    result, processing_load_signal = await _call_coach(
        state.session,
        lambda: state.language_coach.pronunciation_feedback(
            state.profile,
            state.session,
            heard_text=transcription.heard_text,
            target_text=target_text,
            match_quality=quality,
            low_confidence_words=transcription.low_confidence_words,
        ),
    )
    return _with_processing_load(result.model_dump(), processing_load_signal)
