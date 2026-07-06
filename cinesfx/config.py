"""Configuration loading and validation.

Non-secret settings come from a YAML file (``config.yaml``); secrets come from the
environment (loaded from ``.env`` when present). Nothing secret is ever stored in
the config object's ``raw`` mapping that gets logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

try:  # python-dotenv is optional at runtime but recommended.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - handled gracefully
    load_dotenv = None  # type: ignore[assignment]


VALID_BRAINS = ("gemini", "openai", "claude")
VALID_SOUND_PROVIDERS = (
    "epidemic",
    "artlist",
    "audiio",
    "musicbed",
    "splice",
    "soundly",
    "freesound",
    "local",
)


class ConfigError(ValueError):
    """Raised when configuration is missing or invalid."""


def _expand(path_value: Optional[str]) -> Optional[Path]:
    """Expand ``~`` and env vars in a path string; return ``None`` if empty."""
    if not path_value:
        return None
    return Path(os.path.expanduser(os.path.expandvars(path_value)))


@dataclass
class AppConfig:
    """Validated application configuration.

    ``raw`` holds only non-secret settings and is safe to log. Secrets are read on
    demand via :meth:`secret`.
    """

    brain: str
    sound_provider: str
    raw: dict[str, Any] = field(default_factory=dict)

    # ---- convenience accessors -------------------------------------------------

    def brain_settings(self) -> dict[str, Any]:
        return dict(self.raw.get("brains", {}).get(self.brain, {}))

    def sound_settings(self) -> dict[str, Any]:
        return dict(self.raw.get("sound_providers", {}).get(self.sound_provider, {}))

    def analysis(self) -> dict[str, Any]:
        return dict(self.raw.get("analysis", {}))

    def placement(self) -> dict[str, Any]:
        return dict(self.raw.get("placement", {}))

    def spatial(self) -> dict[str, Any]:
        return dict(self.raw.get("spatial", {}))

    def runtime(self) -> dict[str, Any]:
        return dict(self.raw.get("runtime", {}))

    def cache_dir(self) -> Path:
        raw_dir = self.runtime().get("cache_dir", "~/.cache/cinesfx")
        expanded = _expand(raw_dir) or Path.home() / ".cache" / "cinesfx"
        expanded.mkdir(parents=True, exist_ok=True)
        return expanded

    def library_path(self) -> Optional[Path]:
        """Return the local library path for folder-based sound providers."""
        return _expand(self.sound_settings().get("library_path"))

    @staticmethod
    def secret(env_key: str) -> Optional[str]:
        """Read a secret from the environment; returns ``None`` if unset/blank."""
        value = os.environ.get(env_key, "").strip()
        return value or None

    def require_secret(self, env_key: str) -> str:
        """Return a required secret or raise a clear, actionable error."""
        value = self.secret(env_key)
        if not value:
            raise ConfigError(
                f"Missing required secret '{env_key}'. Add it to your .env file "
                f"(see .env.example)."
            )
        return value


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Return ``base`` deep-merged with ``overrides`` (overrides win).

    Nested dicts are merged recursively; scalar/list values are replaced. Neither
    input is mutated.
    """
    result = dict(base)
    for key, value in overrides.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = deep_merge(existing, value)
        else:
            result[key] = value
    return result


def load_config(
    config_path: Optional[str] = None,
    env_path: Optional[str] = None,
    use_user_settings: bool = True,
) -> AppConfig:
    """Load and validate configuration from YAML + user settings + environment.

    Precedence (lowest to highest): ``config.yaml`` → persisted UI user settings
    → this call's explicit arguments. This is what lets a user pick a brain /
    sound provider once in the UI and have it remembered, while still being able
    to change it again later.

    Args:
        config_path: Path to ``config.yaml``. Defaults to ``./config.yaml`` and
            falls back to ``config.example.yaml`` so the tool is runnable
            out-of-the-box for previews.
        env_path: Optional path to a ``.env`` file to load.
        use_user_settings: When True, overlay the user's saved UI settings.

    Returns:
        A validated :class:`AppConfig`.

    Raises:
        ConfigError: If the file is missing/invalid or a selection is unknown.
    """
    if load_dotenv is not None:
        load_dotenv(env_path or ".env", override=False)

    resolved = _resolve_config_file(config_path)
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError as exc:
        raise ConfigError(
            "No config file found. Copy config.example.yaml to config.yaml."
        ) from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse config file '{resolved}': {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Config root must be a mapping.")

    if use_user_settings:
        data = _overlay_user_settings(data)

    brain = str(data.get("brain", "gemini")).lower()
    if brain not in VALID_BRAINS:
        raise ConfigError(
            f"Unknown brain '{brain}'. Choose one of: {', '.join(VALID_BRAINS)}."
        )

    sound_provider = str(data.get("sound_provider", "freesound")).lower()
    if sound_provider not in VALID_SOUND_PROVIDERS:
        raise ConfigError(
            f"Unknown sound_provider '{sound_provider}'. Choose one of: "
            f"{', '.join(VALID_SOUND_PROVIDERS)}."
        )

    return AppConfig(brain=brain, sound_provider=sound_provider, raw=data)


def _resolve_config_file(config_path: Optional[str]) -> Path:
    """Pick the config file to use, preferring the user's real config."""
    if config_path:
        return Path(config_path)
    local = Path("config.yaml")
    if local.exists():
        return local
    return Path("config.example.yaml")


def _overlay_user_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge persisted UI settings over the YAML config, if available."""
    try:
        from cinesfx.settings import UserSettings

        overrides = UserSettings.load().as_override_dict()
    except Exception:  # noqa: BLE001 - settings are optional; never block load
        return data
    return deep_merge(data, overrides) if overrides else data
