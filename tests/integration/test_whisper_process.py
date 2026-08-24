"""Exercises WhisperProcessManager against a fake `whisper-stream` script
instead of the real binary, per docs/TEST_PLAN.md."""

import sys
import textwrap

import pytest

from meeting_copilot.audio.whisper_process import WhisperProcessManager, build_command
from meeting_copilot.config import WhisperSettings


def test_build_command_includes_language_flag(tmp_path):
    """Regression test: `-l`/`--language` existed on WhisperSettings but was
    never actually passed to the subprocess until 2026-07-22 -- silently
    invisible with the English-only model (which can't produce anything but
    English regardless), but a real bug once a second, multilingual-model
    WhisperProcessManager needed `-l pt` to transcribe Portuguese instead of
    defaulting to English (see session_service.py's reverse pipeline)."""
    settings = WhisperSettings(
        repository_path=str(tmp_path),
        binary_path=str(tmp_path / "whisper-stream"),
        model_path=str(tmp_path / "ggml-small.bin"),
        language="pt",
    )
    command = build_command(settings)
    assert "-l" in command
    assert command[command.index("-l") + 1] == "pt"


def test_build_command_defaults_to_english(tmp_path):
    settings = WhisperSettings(
        repository_path=str(tmp_path),
        binary_path=str(tmp_path / "whisper-stream"),
        model_path=str(tmp_path / "ggml-small.en.bin"),
    )
    command = build_command(settings)
    assert command[command.index("-l") + 1] == "en"


def _write_fake_binary(tmp_path, script: str):
    binary = tmp_path / "whisper-stream"
    binary.write_text(f"#!{sys.executable}\n{textwrap.dedent(script)}")
    binary.chmod(0o755)
    return binary


async def test_iter_transcript_lines_yields_cleaned_text(tmp_path):
    binary = _write_fake_binary(
        tmp_path,
        """
        import sys
        print("[00:00:01.000 --> 00:00:02.000] Hello from the fake stream.")
        sys.stdout.flush()
        """,
    )
    model = tmp_path / "ggml-small.en.bin"
    model.write_bytes(b"fake")

    settings = WhisperSettings(
        repository_path=str(tmp_path),
        binary_path=str(binary),
        model_path=str(model),
    )
    manager = WhisperProcessManager(settings)

    lines = []
    async for text in manager.iter_transcript_lines():
        lines.append(text)
        if len(lines) >= 1:
            break

    assert lines == ["Hello from the fake stream."]
    await manager.stop()


async def test_validate_whisper_setup_raises_when_binary_missing(tmp_path):
    from meeting_copilot.audio.whisper_process import WhisperBinaryNotFound, validate_whisper_setup

    settings = WhisperSettings(
        repository_path=str(tmp_path),
        binary_path=str(tmp_path / "does-not-exist"),
        model_path=str(tmp_path / "does-not-exist.bin"),
    )
    with pytest.raises(WhisperBinaryNotFound):
        validate_whisper_setup(settings)
