"""Tests for the UI-managed credential store and the connection registry."""

import os

import pytest

from cinesfx.config import VALID_BRAINS, VALID_SOUND_PROVIDERS, AppConfig
from cinesfx.connections import (
    BRAIN_CONNECTIONS,
    SOUND_CONNECTIONS,
    connect_brain,
    connect_sound,
    save_sound_inputs,
)
from cinesfx.credentials import CredentialStore, get_credential
from cinesfx.settings import UserSettings


@pytest.fixture(autouse=True)
def isolated_config_dir(tmp_path, monkeypatch):
    """Point the per-user config dir at a temp folder for every test."""
    monkeypatch.setenv("CINESFX_CONFIG_DIR", str(tmp_path / "cfg"))
    yield


# --------------------------------------------------------------- credential store


def test_credential_store_round_trip():
    store = CredentialStore()
    assert store.get("GEMINI_API_KEY") is None

    store.set("GEMINI_API_KEY", "  secret-key  ")
    assert store.get("GEMINI_API_KEY") == "secret-key"  # trimmed
    assert store.has("GEMINI_API_KEY")
    assert store.all() == {"GEMINI_API_KEY": "secret-key"}

    store.delete("GEMINI_API_KEY")
    assert store.get("GEMINI_API_KEY") is None


def test_credential_store_ignores_blank_values():
    store = CredentialStore()
    store.set_many({"A": "value", "B": "", "C": "   "})
    assert store.all() == {"A": "value"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file permissions only")
def test_credential_file_is_owner_only():
    store = CredentialStore()
    store.set("OPENAI_API_KEY", "sk-test")
    mode = store.path.stat().st_mode & 0o777
    assert mode == 0o600


# ------------------------------------------------------------- config.secret order


def test_secret_prefers_environment(monkeypatch):
    CredentialStore().set("OPENAI_API_KEY", "from-store")
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert AppConfig.secret("OPENAI_API_KEY") == "from-env"


def test_secret_falls_back_to_store(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    CredentialStore().set("ANTHROPIC_API_KEY", "from-store")
    assert AppConfig.secret("ANTHROPIC_API_KEY") == "from-store"
    assert get_credential("ANTHROPIC_API_KEY") == "from-store"


# ---------------------------------------------------------------- registry sanity


def test_registry_names_match_config_choices():
    assert set(BRAIN_CONNECTIONS) == set(VALID_BRAINS)
    assert set(SOUND_CONNECTIONS) == set(VALID_SOUND_PROVIDERS)
    for conn in {**BRAIN_CONNECTIONS, **SOUND_CONNECTIONS}.values():
        assert conn.label
        for field in conn.fields:
            assert field.key and field.label


# ----------------------------------------------------------------- connect logic


def test_connect_brain_saves_key_and_selects(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = connect_brain("gemini", {"GEMINI_API_KEY": "test-key"})
    assert result.ok, result.message
    assert get_credential("GEMINI_API_KEY") == "test-key"
    assert UserSettings.load().brain == "gemini"


def test_connect_brain_without_key_reports_not_connected(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = connect_brain("gemini", {"GEMINI_API_KEY": ""})
    assert not result.ok
    assert "Not connected" in result.message


def test_connect_sound_folder_saves_override(tmp_path):
    folder = tmp_path / "sfx"
    folder.mkdir()
    (folder / "boom.wav").write_bytes(b"x")

    result = connect_sound("local", {"library_path": str(folder)})
    assert result.ok, result.message

    settings = UserSettings.load()
    assert settings.sound_provider == "local"
    assert settings.provider_overrides["local"]["library_path"] == str(folder)


def test_connect_sound_catalog_parses_roots(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    result = connect_sound("catalog", {"roots": f"{a}, {b}"})
    assert result.ok, result.message

    roots = UserSettings.load().provider_overrides["catalog"]["roots"]
    assert roots == [str(a), str(b)]


def test_save_sound_inputs_persists_without_selecting(monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    save_sound_inputs("freesound", {"FREESOUND_API_KEY": "free-token"})
    assert get_credential("FREESOUND_API_KEY") == "free-token"
    # Saving inputs must not flip the active provider (only Connect does).
    assert UserSettings.load().sound_provider is None
