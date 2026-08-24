"""POST /api/translate/* -- standalone translation utilities.

Distinct from api/language_coach.py on purpose: this is literal, fast
NMT translation of exactly what was said, not LLM-coached rephrasing
(the existing "Ideia opcional em português" footer bar already covers
that, via the Meeting Coach). Doesn't touch Ollama at all, so no
coach_busy_count gating.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from meeting_copilot.context.language_detect import detect_language
from meeting_copilot.context.opus_mt import translate_en_to_pt_br, translate_pt_to_en
from meeting_copilot.context.pt_speech import PortugueseSpeechError, transcribe_portuguese

router = APIRouter()


class DetectLanguageRequest(BaseModel):
    text: str


class TranslateTextRequest(BaseModel):
    text: str


@router.post("/api/translate/detect-language")
async def detect_language_route(body: DetectLanguageRequest) -> dict[str, Literal["en", "pt"]]:
    """Cheap EN-vs-PT-BR guess for the "Ideia opcional" footer box, so it
    can auto-route to the right translation direction instead of always
    assuming Portuguese input. See context/language_detect.py.
    """
    return {"language": detect_language(body.text)}


@router.post("/api/translate/en-to-pt")
async def translate_en_to_pt_route(request: Request, body: TranslateTextRequest) -> dict[str, str]:
    """Literal EN->PT-BR translation for the "Ideia opcional" box when the
    typed text is detected as English -- the reverse of that box's
    existing PT->EN flow (which stays LLM-coached, unchanged, via
    /api/actions/suggest-answer). Fast, no Ollama involved.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text não pode ser vazio.")
    state = request.app.state.copilot
    glossary_terms = tuple(state.glossary.get("terms", {}).keys())
    translated = await translate_en_to_pt_br(text, state.settings.translation.opus_mt_en_pt_dir_expanded, glossary_terms)
    return {"translated_pt": translated}


@router.post("/api/translate/speak-portuguese")
async def speak_portuguese(request: Request, audio: UploadFile = File(...)) -> dict[str, str]:
    """"Falar em português" -- one-shot PT speech recognition + PT->EN translation.

    Uses a separate multilingual whisper-cli call (never the continuous
    whisper-stream process the live meeting uses), so this can't affect
    English transcription performance -- see context/pt_speech.py.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Áudio vazio.")

    state = request.app.state.copilot
    try:
        heard_pt = await transcribe_portuguese(audio_bytes, state.settings.whisper)
    except PortugueseSpeechError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not heard_pt.strip():
        return {"heard_pt": "", "translated_en": ""}

    translated_en = await translate_pt_to_en(heard_pt, state.settings.translation.opus_mt_pt_en_dir_expanded)
    return {"heard_pt": heard_pt, "translated_en": translated_en}
