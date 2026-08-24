"""Shared pytest fixtures.

Adds src/ to sys.path directly (in addition to whatever `pip install -e .`
does) so tests keep working even if the package was not installed in the
current environment -- useful in constrained sandboxes.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pytest  # noqa: E402

from meeting_copilot.config import OllamaSettings, PrivacySettings, ServerSettings, Settings, WhisperSettings  # noqa: E402


@pytest.fixture
def whisper_settings(tmp_path) -> WhisperSettings:
    binary = tmp_path / "whisper-stream"
    binary.write_text("#!/bin/sh\necho fake\n")
    binary.chmod(0o755)
    model = tmp_path / "ggml-small.en.bin"
    model.write_bytes(b"fake-model-bytes")
    return WhisperSettings(
        repository_path=str(tmp_path),
        binary_path=str(binary),
        model_path=str(model),
        rolling_window_seconds=90,
    )


@pytest.fixture
def settings(whisper_settings) -> Settings:
    return Settings(
        server=ServerSettings(),
        privacy=PrivacySettings(),
        whisper=whisper_settings,
        ollama=OllamaSettings(),
    )


@pytest.fixture
def architecture_meeting_text() -> str:
    fixture_path = REPO_ROOT / "tests" / "fixtures" / "architecture_meeting.txt"
    return fixture_path.read_text(encoding="utf-8")
