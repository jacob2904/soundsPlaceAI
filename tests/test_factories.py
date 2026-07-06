"""Tests that the factories select providers and fail with clear errors."""

import pytest

from cinesfx.brain.base import BrainError
from cinesfx.brain.factory import create_brain
from cinesfx.config import AppConfig
from cinesfx.sound.base import SoundProviderError
from cinesfx.sound.factory import create_sound_provider


def _config(brain="gemini", sound="freesound", raw=None):
    return AppConfig(brain=brain, sound_provider=sound, raw=raw or {})


def test_brain_factory_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(BrainError):
        create_brain(_config(brain="gemini"))


def test_sound_factory_freesound_requires_key(monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    with pytest.raises(SoundProviderError):
        create_sound_provider(_config(sound="freesound"))


def test_sound_factory_partner_requires_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("ARTLIST_API_BASE", raising=False)
    monkeypatch.delenv("ARTLIST_API_TOKEN", raising=False)
    config = _config(
        sound="artlist",
        raw={"runtime": {"cache_dir": str(tmp_path)}},
    )
    with pytest.raises(SoundProviderError):
        create_sound_provider(config)


def test_sound_factory_local_requires_library(tmp_path):
    config = _config(
        sound="local",
        raw={
            "runtime": {"cache_dir": str(tmp_path)},
            "sound_providers": {"local": {}},
        },
    )
    with pytest.raises(SoundProviderError):
        create_sound_provider(config)
