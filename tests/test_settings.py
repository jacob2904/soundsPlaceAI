"""Tests for persistent user settings and config overlay."""

import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cinesfx.config import deep_merge, load_config
from cinesfx.licensing import build_payload, encode_license
from cinesfx.settings import (
    UserSettings,
    activate_license,
    get_license_status,
)


def test_deep_merge_overrides_win_and_nested_merge():
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "keep": True}
    override = {"a": 9, "nested": {"y": 20, "z": 30}}
    merged = deep_merge(base, override)
    assert merged["a"] == 9
    assert merged["nested"] == {"x": 1, "y": 20, "z": 30}
    assert merged["keep"] is True
    # inputs are not mutated
    assert base["a"] == 1


def test_settings_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CINESFX_CONFIG_DIR", str(tmp_path))
    settings = UserSettings(brain="claude", sound_provider="soundly", scope="all")
    settings.set_provider_override("soundly", "library_path", "/my/soundly")
    settings.save()

    loaded = UserSettings.load()
    assert loaded.brain == "claude"
    assert loaded.sound_provider == "soundly"
    assert loaded.scope == "all"
    assert loaded.provider_overrides["soundly"]["library_path"] == "/my/soundly"


def test_settings_override_dict_shape():
    settings = UserSettings(brain="openai", sound_provider="local")
    settings.set_provider_override("local", "library_path", "/sfx")
    override = settings.as_override_dict()
    assert override["brain"] == "openai"
    assert override["sound_provider"] == "local"
    assert override["sound_providers"]["local"]["library_path"] == "/sfx"


def test_user_settings_overlay_changes_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CINESFX_CONFIG_DIR", str(tmp_path))
    config_file = tmp_path / "config.yaml"
    config_file.write_text("brain: gemini\nsound_provider: freesound\n", encoding="utf-8")

    # Save a UI choice that should override the YAML.
    UserSettings(brain="claude", sound_provider="local").save()

    config = load_config(config_path=str(config_file), use_user_settings=True)
    assert config.brain == "claude"
    assert config.sound_provider == "local"

    # And it can be ignored when requested.
    config_plain = load_config(config_path=str(config_file), use_user_settings=False)
    assert config_plain.brain == "gemini"


def _demo_license(licensee="demo@studio.com") -> str:
    demo_private_b64 = "jrDMWPf7PHlQyX4uqt9wL4kS2ZvP_WnS7sbMsSEAVa8="
    private = Ed25519PrivateKey.from_private_bytes(
        base64.urlsafe_b64decode(demo_private_b64)
    )
    payload = build_payload(licensee)
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return encode_license(payload, private.sign(canonical))


def test_activation_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("CINESFX_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("CINESFX_LICENSE_KEY", raising=False)

    assert get_license_status().activated is False

    status = activate_license(_demo_license())
    assert status.activated is True

    # Persisted: a fresh status read still sees it activated.
    assert get_license_status().activated is True
