from pathlib import Path

import pytest

from meeting_copilot.config import TranslationSettings
from meeting_copilot.context.opus_mt import (
    _protect_and_translate,
    translate_en_to_pt_br,
    translate_pt_to_en,
)

EN_PT_BR_MODEL_DIR = Path("~/Developer/opus-mt-models/en-pt-br").expanduser()
PT_EN_MODEL_DIR = Path("~/Developer/opus-mt-models/pt-en").expanduser()

_models_available = EN_PT_BR_MODEL_DIR.exists() and PT_EN_MODEL_DIR.exists()
requires_models = pytest.mark.skipif(
    not _models_available,
    reason="OPUS-MT models not downloaded on this machine -- run scripts/download_pt_br_translation_models.sh",
)


class _FakeModel:
    """Records the exact text handed to translate() and echoes it back,
    so protection/restoration logic can be tested without loading a
    real ctranslate2 model."""

    def __init__(self):
        self.received: str | None = None

    def translate(self, text: str) -> str:
        self.received = text
        return text


def test_protect_and_translate_shields_pause_markers():
    model = _FakeModel()
    _protect_and_translate(model, "Hello [pausa: 4.2s] world", glossary_terms=())
    assert "[pausa: 4.2s]" not in model.received
    assert "ZZPROTECTEDZZ" in model.received


def test_protect_and_translate_restores_pause_markers_in_output():
    model = _FakeModel()
    result = _protect_and_translate(model, "Hello [pausa: 4.2s] world", glossary_terms=())
    assert result == "Hello [pausa: 4.2s] world"


def test_protect_and_translate_shields_glossary_terms():
    model = _FakeModel()
    result = _protect_and_translate(model, "We discussed Kubernetes today", glossary_terms=("Kubernetes",))
    assert "Kubernetes" not in model.received
    assert result == "We discussed Kubernetes today"


def test_protect_and_translate_ignores_absent_glossary_terms():
    model = _FakeModel()
    result = _protect_and_translate(model, "Plain text", glossary_terms=("SLO", "Kubernetes"))
    assert result == "Plain text"


class _MangledTokenModel:
    """Simulates the empirically-observed failure (a real session,
    2026-08-12) where the NMT model doesn't preserve the protection
    token intact through SentencePiece tokenization + beam search --
    drops one "Z" from the "ZZPROTECTEDZZ" run but leaves the digit
    untouched, producing "ZZPROTECTEDZ0ZZ" instead of the real
    "ZZPROTECTEDZZ0ZZ". That mangled text leaked straight into the
    PT-BR shown to the user before this fallback existed."""

    def translate(self, text: str) -> str:
        return text.replace("ZZPROTECTEDZZ", "ZZPROTECTEDZ", 1)


def test_protect_and_translate_recovers_original_when_token_letters_get_mangled():
    model = _MangledTokenModel()
    result = _protect_and_translate(model, "Hello [pausa: 4.2s] world", glossary_terms=())
    assert result == "Hello [pausa: 4.2s] world"
    assert "PROTECTED" not in result


class _UnrecoverableTokenModel:
    """The token survives as a recognizable shape but with a digit that
    was never assigned by protect() (only index 0 exists here) -- the
    truly unrecoverable case, since there's no original text to map it
    back to."""

    def translate(self, text: str) -> str:
        return "Some text ZZPROTECTEDZZ99ZZ end"


def test_protect_and_translate_falls_back_to_placeholder_when_unrecoverable():
    model = _UnrecoverableTokenModel()
    result = _protect_and_translate(model, "Hello [pausa: 4.2s] world", glossary_terms=())
    assert "[não traduzido]" in result
    assert "PROTECTED" not in result


@requires_models
class TestRealModels:
    """Guards against regressing the two real bugs found integrating these
    models: (1) the >>pob<< tag must be a pre-existing token, never run
    through sp.encode(), or output degenerates into repetition/leaked tag
    text; (2) the source sequence needs an explicit trailing </s>, or the
    PT->EN model loops indefinitely even on trivial input."""

    @pytest.mark.asyncio
    async def test_en_to_pt_br_produces_brazilian_not_european_vocabulary(self):
        result = await translate_en_to_pt_br("I am going to the bathroom.", EN_PT_BR_MODEL_DIR)
        assert "banheiro" in result.lower()
        assert "casa de banho" not in result.lower()

    @pytest.mark.asyncio
    async def test_en_to_pt_br_does_not_leak_the_tag_or_repeat(self):
        result = await translate_en_to_pt_br("The train is late again.", EN_PT_BR_MODEL_DIR)
        assert ">>" not in result
        assert "pob" not in result.lower()
        # A crude repetition guard: the same 3-word phrase shouldn't appear twice.
        words = result.lower().split()
        trigrams = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
        assert len(trigrams) == len(set(trigrams))

    @pytest.mark.asyncio
    async def test_pt_to_en_translates_correctly(self):
        result = await translate_pt_to_en("Você pode me dar uma carona até o aeroporto?", PT_EN_MODEL_DIR)
        assert "ride" in result.lower() or "lift" in result.lower()
        assert "airport" in result.lower()

    @pytest.mark.asyncio
    async def test_pt_to_en_does_not_repeat(self):
        result = await translate_pt_to_en("Bom dia, vamos começar a reunião.", PT_EN_MODEL_DIR)
        words = result.lower().split()
        trigrams = [" ".join(words[i : i + 3]) for i in range(len(words) - 2)]
        assert len(trigrams) == len(set(trigrams))


def test_translation_settings_default_paths_point_under_developer():
    settings = TranslationSettings()
    assert settings.opus_mt_en_pt_dir_expanded.name == "en-pt-br"
    assert settings.opus_mt_pt_en_dir_expanded.name == "pt-en"
    assert "~" not in str(settings.opus_mt_en_pt_dir_expanded)
