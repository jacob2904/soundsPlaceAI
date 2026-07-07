"""Local, UI-managed credential store.

Lets the end user connect their brain / sound provider **from the panel** by
entering a key once and clicking *Connect* — no manual ``.env`` editing required.

Keys are saved to a single JSON file in the per-user config directory
(``connections.json``), with owner-only file permissions where the OS supports it.
This is a local secret store (not committed, not in code); it is consulted by
:meth:`cinesfx.config.AppConfig.secret` as a fallback *after* real environment
variables, so a ``.env`` / real env var still wins if present, and everything
(panel and CLI) transparently picks up UI-entered credentials.

Security: values are never logged (logging is redacted), the file is written with
``0600`` perms, and nothing here ever prints a secret.
"""

from __future__ import annotations

import os
from pathlib import Path

from cinesfx.logging_utils import get_logger
from cinesfx.user_store import read_json, user_config_dir, write_json

_log = get_logger("credentials")

_CREDENTIALS_FILE = "connections.json"


class CredentialStore:
    """Read/write locally-stored API credentials keyed by their env-var name."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (user_config_dir() / _CREDENTIALS_FILE)

    @property
    def path(self) -> Path:
        return self._path

    def all(self) -> dict[str, str]:
        """Return every stored credential (env key → value)."""
        data = read_json(self._path)
        return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and v}

    def get(self, env_key: str) -> str | None:
        """Return one stored credential, or ``None`` if not set."""
        value = self.all().get(env_key)
        return value or None

    def has(self, env_key: str) -> bool:
        return bool(self.get(env_key))

    def set_many(self, values: dict[str, str]) -> None:
        """Store several credentials at once (blank/None values are ignored)."""
        data = self.all()
        changed = False
        for key, value in values.items():
            cleaned = (value or "").strip()
            if cleaned:
                data[key] = cleaned
                changed = True
        if changed:
            self._write(data)

    def set(self, env_key: str, value: str) -> None:
        """Store a single credential."""
        self.set_many({env_key: value})

    def delete(self, env_key: str) -> None:
        """Remove a stored credential (no error if it was absent)."""
        data = self.all()
        if data.pop(env_key, None) is not None:
            self._write(data)

    def _write(self, data: dict[str, str]) -> None:
        write_json(self._path, data)
        self._restrict_permissions()

    def _restrict_permissions(self) -> None:
        """Best-effort owner-only file permissions (no-op on unsupported OSes)."""
        try:
            os.chmod(self._path, 0o600)
        except OSError as exc:  # pragma: no cover - platform dependent
            _log.debug("Could not set permissions on %s: %s", self._path, exc)


def get_credential(env_key: str) -> str | None:
    """Return a stored credential by env-var name (module-level convenience)."""
    try:
        return CredentialStore().get(env_key)
    except Exception as exc:  # noqa: BLE001 - never let credential lookup crash
        _log.debug("Credential lookup for %s failed: %s", env_key, exc)
        return None
