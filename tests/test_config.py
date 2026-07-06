"""Tests for configuration loading and validation."""

import pytest

from cinesfx.config import AppConfig, ConfigError, load_config


def _write(tmp_path, text: str):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_load_valid_config(tmp_path, monkeypatch):
    path = _write(
        tmp_path,
        "brain: openai\nsound_provider: freesound\n"
        "brains:\n  openai:\n    model: gpt-4o\n"
        "runtime:\n  cache_dir: %s\n" % (tmp_path / "cache"),
    )
    config = load_config(config_path=path)
    assert config.brain == "openai"
    assert config.sound_provider == "freesound"
    assert config.brain_settings()["model"] == "gpt-4o"
    assert config.cache_dir().exists()


def test_unknown_brain_raises(tmp_path):
    path = _write(tmp_path, "brain: hal9000\nsound_provider: freesound\n")
    with pytest.raises(ConfigError):
        load_config(config_path=path)


def test_unknown_sound_provider_raises(tmp_path):
    path = _write(tmp_path, "brain: gemini\nsound_provider: napster\n")
    with pytest.raises(ConfigError):
        load_config(config_path=path)


def test_secret_reads_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert AppConfig.secret("OPENAI_API_KEY") == "sk-test"


def test_require_secret_raises_when_missing(monkeypatch):
    monkeypatch.delenv("NON_EXISTENT_KEY", raising=False)
    config = AppConfig(brain="gemini", sound_provider="freesound")
    with pytest.raises(ConfigError):
        config.require_secret("NON_EXISTENT_KEY")
