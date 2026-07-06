"""Persistent, changeable end-user settings.

Anything the user picks in the UI (brain, sound provider, scope, provider paths,
etc.) is stored here so it is remembered next time — and can be changed again at
any point. These overrides are layered *on top of* ``config.yaml`` so power users
can still keep advanced defaults in YAML while the UI drives the common choices.

The activated license key is stored here too (separate ``license.json`` file).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from cinesfx.user_store import read_json, user_config_dir, write_json

_SETTINGS_FILE = "settings.json"
_LICENSE_FILE = "license.json"

# Keys the UI is allowed to persist as top-level overrides.
_TOP_LEVEL_KEYS = ("brain", "sound_provider", "scope", "dry_run", "color")


@dataclass
class UserSettings:
    """User preference overlay persisted to the per-user config directory."""

    brain: Optional[str] = None
    sound_provider: Optional[str] = None
    scope: str = "current"
    dry_run: bool = True
    color: str = "Orange"
    # Per-provider setting overrides, e.g. {"soundly": {"library_path": "..."}}.
    provider_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-brain setting overrides, e.g. {"gemini": {"model": "gemini-2.5-pro"}}.
    brain_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return user_config_dir() / _SETTINGS_FILE

    # ------------------------------------------------------------------ load/save

    @classmethod
    def load(cls) -> "UserSettings":
        """Load settings from disk (returns defaults if none saved yet)."""
        data = read_json(user_config_dir() / _SETTINGS_FILE)
        return cls(
            brain=data.get("brain"),
            sound_provider=data.get("sound_provider"),
            scope=str(data.get("scope", "current")),
            dry_run=bool(data.get("dry_run", True)),
            color=str(data.get("color", "Orange")),
            provider_overrides=dict(data.get("provider_overrides", {})),
            brain_overrides=dict(data.get("brain_overrides", {})),
        )

    def save(self) -> Path:
        """Persist settings to disk and return the file path."""
        payload = {
            "brain": self.brain,
            "sound_provider": self.sound_provider,
            "scope": self.scope,
            "dry_run": self.dry_run,
            "color": self.color,
            "provider_overrides": self.provider_overrides,
            "brain_overrides": self.brain_overrides,
        }
        path = user_config_dir() / _SETTINGS_FILE
        write_json(path, payload)
        return path

    # ------------------------------------------------------------------ mutation

    def set_provider_override(self, provider: str, key: str, value: Any) -> None:
        """Set (or clear, if value is falsy) a per-provider setting override."""
        bucket = self.provider_overrides.setdefault(provider, {})
        if value in (None, ""):
            bucket.pop(key, None)
        else:
            bucket[key] = value

    def as_override_dict(self) -> dict[str, Any]:
        """Return a config-shaped mapping to overlay onto ``config.yaml`` data."""
        overrides: dict[str, Any] = {}
        if self.brain:
            overrides["brain"] = self.brain
        if self.sound_provider:
            overrides["sound_provider"] = self.sound_provider
        if self.provider_overrides:
            overrides["sound_providers"] = self.provider_overrides
        if self.brain_overrides:
            overrides["brains"] = self.brain_overrides
        return overrides


def save_license_key(key: str) -> Path:
    """Persist an activated license key. Returns the file path."""
    path = user_config_dir() / _LICENSE_FILE
    write_json(path, {"key": key.strip()})
    return path


def load_license_key() -> Optional[str]:
    """Return the stored license key, or ``None`` if not activated.

    Honours the ``CINESFX_LICENSE_KEY`` environment variable first, so licenses
    can also be injected via a secret manager.
    """
    import os

    env_key = os.environ.get("CINESFX_LICENSE_KEY", "").strip()
    if env_key:
        return env_key
    data = read_json(user_config_dir() / _LICENSE_FILE)
    key = data.get("key")
    return key.strip() if isinstance(key, str) and key.strip() else None


@dataclass(frozen=True)
class LicenseStatus:
    """The current activation state, safe to show in the UI."""

    activated: bool
    message: str
    licensee: Optional[str] = None


def get_license_status() -> LicenseStatus:
    """Return the current license status by verifying any stored key."""
    from cinesfx.licensing import LicenseError, verify_license

    key = load_license_key()
    if not key:
        return LicenseStatus(False, "Not activated — running in free preview mode.")
    try:
        info = verify_license(key)
    except LicenseError as exc:
        return LicenseStatus(False, f"License problem: {exc}")
    return LicenseStatus(True, f"Activated · {info.summary()}", licensee=info.licensee)


def activate_license(key: str) -> LicenseStatus:
    """Verify and persist a license key. Returns the resulting status.

    Raises:
        LicenseError: If the key is invalid (nothing is saved in that case).
    """
    from cinesfx.licensing import verify_license

    info = verify_license(key)  # raises LicenseError on failure (not saved)
    save_license_key(key)
    return LicenseStatus(True, f"Activated · {info.summary()}", licensee=info.licensee)
