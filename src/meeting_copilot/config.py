"""Loading and validating configuration from config/*.yaml.

Design notes
------------
- All paths that may contain "~" are expanded with os.path.expanduser.
- Nothing here reaches out to the network.
- Settings are re-read on demand (``load_settings()``) rather than cached
  as module globals, so the /api/config endpoints can hot-reload files the
  user edited by hand or through the UI.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

# The repository root is two levels above this file:
# src/meeting_copilot/config.py -> src/meeting_copilot -> src -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
PROMPTS_DIR = REPO_ROOT / "prompts"


def _expand(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value))


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a YAML mapping at top level in {path}")
    return data


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class PrivacySettings(BaseModel):
    persist_audio: bool = False
    persist_transcript: bool = False
    persist_summary: bool = False
    # Opt-in, off by default. When true, the PT-BR translation stream and
    # the derived meeting summary are appended to a local markdown file
    # under data/sessions/ (never the raw audio or raw English transcript,
    # and never sent anywhere off this machine). See docs/PRIVACY.md.
    persist_learning_notes: bool = False
    redact_logs: bool = True
    allow_external_network: bool = False


class WhisperSettings(BaseModel):
    repository_path: str
    binary_path: str
    model_path: str
    language: str = "en"
    threads: int = 6
    step_ms: int = 500
    length_ms: int = 5000
    rolling_window_seconds: int = 90
    capture_device: int = -1
    # Multilingual model (NOT the English-only model_path above). Used by:
    # (a) the one-shot "Falar em português" whisper-cli call
    # (context/pt_speech.py, still available as a standalone utility), and
    # (b) a SECOND, independent continuous whisper-stream process
    # (services/session_service.py) that listens for Portuguese speech
    # live, the same way the main whisper-stream listens for English --
    # see `enable_portuguese_stream` below. This second stream never
    # touches the main English WhisperProcessManager/model, so it can't
    # degrade English transcription accuracy; it's a genuinely separate
    # process reading the same capture device (confirmed empirically that
    # macOS/SDL2 allows two concurrent capture sessions on one device).
    # Download via: cd <repository_path> && sh ./models/download-ggml-model.sh small
    multilingual_model_path: str = "~/Developer/whisper.cpp/models/ggml-small.bin"
    # Runs a second, continuous whisper-stream process (multilingual model,
    # -l pt) alongside the main English one, both reading the same capture
    # device -- real, measured CPU cost, not free. Needed whenever a single
    # mic captures both your own voice and room/meeting audio (your voice
    # isn't otherwise isolated on a separate device), for "speaks
    # Portuguese -> auto-translates to English" to work at all. Set to
    # false to fall back to the one-shot "Falar em português" button only.
    enable_portuguese_stream: bool = True

    @property
    def binary_path_expanded(self) -> Path:
        return Path(_expand(self.binary_path))

    @property
    def model_path_expanded(self) -> Path:
        return Path(_expand(self.model_path))

    @property
    def repository_path_expanded(self) -> Path:
        return Path(_expand(self.repository_path))

    @property
    def multilingual_model_path_expanded(self) -> Path:
        return Path(_expand(self.multilingual_model_path))

    @property
    def cli_binary_path_expanded(self) -> Path:
        # whisper-cli ships alongside whisper-stream in the same build/bin
        # directory (confirmed via `ls`). Used by both context/pronunciation.py
        # and context/pt_speech.py -- lives here, not duplicated in either,
        # since WhisperSettings is the natural owner of every whisper.cpp path.
        return self.binary_path_expanded.parent / "whisper-cli"


class OllamaSettings(BaseModel):
    base_url: str = "http://127.0.0.1:11434"
    # Switched from qwen3:4b on 2026-07-17 -- see config/settings.yaml's
    # ollama.model comment and docs/DECISIONS.md for the benchmark.
    model: str = "llama3.2:3b"
    think: bool = False
    temperature: float = 0.2
    context_tokens: int = 4096
    request_timeout_seconds: int = 90


class SummarizationSettings(BaseModel):
    enabled: bool = True
    interval_seconds: int = 180
    max_summary_characters: int = 2500


class TranslationSettings(BaseModel):
    enabled: bool = True
    # No interval_seconds/min_new_characters -- translation is event-driven
    # (fires per transcript segment), not batched. See TranslationManager.
    # "argos": dedicated local NMT (argostranslate/CTranslate2) -- fast, but
    # its only en->pt package is European Portuguese, not Brazilian
    # (confirmed empirically 2026-07-22, see docs/DECISIONS.md). "opus_mt":
    # Helsinki-NLP OPUS-MT models (also CTranslate2-backed, same speed
    # class) with a real Brazilian-Portuguese target -- see
    # context/opus_mt.py. "ollama": the original LLM-based path, kept as a
    # fallback. See docs/DECISIONS.md, 2026-07-20.
    engine: str = "argos"
    # Only used when engine="ollama". Empty string means "use
    # ollama.model" -- see learning_service.py's make_translate_fn.
    model: str = ""
    # Only used when engine="opus_mt". Filesystem paths to the
    # CTranslate2-converted Helsinki-NLP OPUS-MT models -- not managed by
    # argostranslate's own package system since these aren't Argos-format
    # packages. See context/opus_mt.py and
    # scripts/download_pt_br_translation_models.sh.
    opus_mt_en_pt_dir: str = "~/Developer/opus-mt-models/en-pt-br"
    opus_mt_pt_en_dir: str = "~/Developer/opus-mt-models/pt-en"

    @property
    def opus_mt_en_pt_dir_expanded(self) -> Path:
        return Path(_expand(self.opus_mt_en_pt_dir))

    @property
    def opus_mt_pt_en_dir_expanded(self) -> Path:
        return Path(_expand(self.opus_mt_pt_en_dir))


class UiSettings(BaseModel):
    transcript_max_lines: int = 20
    font_scale: float = 1.0
    show_grammar_explanation: bool = True
    auto_scroll: bool = True


class AutomationSettings(BaseModel):
    detect_direct_questions: bool = True
    auto_generate_answer: bool = False
    trigger_phrases: list[str] = Field(default_factory=list)
    # Noticing Hypothesis (LANGUAGE_COACH_PEDAGOGY.md theory #2) --
    # proactively flags a noticeable idiom/phrasal verb in the live
    # transcript instead of only reacting to a click. Deterministic
    # curated-list lookup (context/noticing_detector.py), no LLM call, so
    # it adds no latency to the transcription pipeline.
    detect_noticeable_language: bool = True
    # Minimum seconds between two noticing.flag broadcasts -- without
    # this, a transcript dense with idioms could pulse the badge every
    # few seconds, which stops being "one-time, predictable motion" and
    # becomes exactly the ambient/ammo-fire attention tax
    # ADHD_NEUROSCIENCE_REFERENCE.md rule #2 warns against.
    noticing_cooldown_seconds: float = 20.0


class Settings(BaseModel):
    server: ServerSettings = ServerSettings()
    privacy: PrivacySettings = PrivacySettings()
    whisper: WhisperSettings
    ollama: OllamaSettings = OllamaSettings()
    summarization: SummarizationSettings = SummarizationSettings()
    translation: TranslationSettings = TranslationSettings()
    ui: UiSettings = UiSettings()
    automation: AutomationSettings = AutomationSettings()


def load_settings(path: Path | None = None) -> Settings:
    """Load config/settings.yaml (or an override path) into a Settings model."""
    raw = _read_yaml(path or (CONFIG_DIR / "settings.yaml"))
    return Settings.model_validate(raw)


def load_profile(path: Path | None = None) -> dict[str, Any]:
    return _read_yaml(path or (CONFIG_DIR / "profile.yaml"))


def load_glossary(path: Path | None = None) -> dict[str, Any]:
    glossary_path = path or (CONFIG_DIR / "glossary.yaml")
    if not glossary_path.exists():
        return {"terms": {}}
    return _read_yaml(glossary_path)


def save_glossary(data: dict[str, Any], path: Path | None = None) -> None:
    glossary_path = path or (CONFIG_DIR / "glossary.yaml")
    with glossary_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def load_prompt(name: str) -> str:
    """Read a prompt template from prompts/<name>.md."""
    prompt_path = PROMPTS_DIR / f"{name}.md"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt template not found: {prompt_path}")
    return prompt_path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor used by FastAPI dependencies.

    Call ``get_settings.cache_clear()`` after editing settings.yaml through
    the API so the next request picks up the change.
    """
    return load_settings()
