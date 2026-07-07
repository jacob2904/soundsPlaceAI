"""Cross-platform user config directory + tiny JSON read/write helpers.

Used to persist the end-user's preferences and their activated license so choices
survive restarts and can be changed at any time.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from cinesfx.logging_utils import get_logger

_log = get_logger("user_store")

_APP_DIR_NAME = "cinesfx"


def user_config_dir() -> Path:
    """Return (and create) the per-user config directory for the app.

    Honours ``CINESFX_CONFIG_DIR`` when set, otherwise uses the OS convention.
    """
    override = os.environ.get("CINESFX_CONFIG_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        base = base / _APP_DIR_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / _APP_DIR_NAME
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = (Path(xdg) if xdg else Path.home() / ".config") / _APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def read_json(path: Path) -> dict[str, Any]:
    """Return a JSON object from ``path`` or ``{}`` if missing/invalid."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("Could not read %s: %s", path, exc)
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` as pretty JSON (atomic-ish via temp file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
        tmp.replace(path)
    except OSError as exc:
        _log.warning("Could not write %s: %s", path, exc)
        raise
