from pathlib import Path

import pytest

from meeting_copilot.config import load_glossary, load_profile, load_settings


def test_load_settings_expands_tilde_paths():
    settings = load_settings()
    assert not str(settings.whisper.binary_path_expanded).startswith("~")
    assert not str(settings.whisper.model_path_expanded).startswith("~")


def test_load_settings_defaults():
    settings = load_settings()
    assert settings.server.host == "127.0.0.1"
    assert settings.privacy.persist_audio is False
    assert settings.privacy.persist_transcript is False
    assert settings.ollama.think is False


def test_load_profile_has_expected_user():
    # config/profile.yaml is gitignored (holds your real name/expertise,
    # never committed) -- test against the checked-in example template
    # instead, which every fresh clone actually has.
    profile = load_profile(Path("config/profile.example.yaml"))
    assert profile["user"]["name"] == "Your Name"
    assert "AWS" in profile["expertise"]


def test_load_glossary_has_expected_terms():
    glossary = load_glossary()
    assert "EKS" in glossary["terms"]


def test_load_settings_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "does-not-exist.yaml")
