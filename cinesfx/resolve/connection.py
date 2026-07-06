"""Establish a connection to a running DaVinci Resolve instance.

Resolve exposes a Python module (``DaVinciResolveScript`` / ``fusionscript``) that
must be importable. When the plugin runs *inside* Resolve (Workflow Integration or
the Console), ``resolve`` is injected automatically. When running standalone (the
CLI), we locate the scripting module using the standard, OS-specific paths that
Blackmagic documents.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any, Optional

from cinesfx.logging_utils import get_logger

_log = get_logger("resolve.connection")


class ResolveConnectionError(RuntimeError):
    """Raised when a Resolve connection cannot be established."""


# Default install locations of the scripting module per OS.
_DEFAULT_MODULE_PATHS = {
    "win32": [
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer"
        r"\Scripting\Modules",
    ],
    "darwin": [
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer"
        "/Scripting/Modules",
    ],
    "linux": [
        "/opt/resolve/Developer/Scripting/Modules",
        "/home/resolve/Developer/Scripting/Modules",
    ],
}


def _candidate_module_dirs() -> list[Path]:
    """Return candidate directories that may contain the scripting module."""
    dirs: list[Path] = []
    env_dir = os.environ.get("RESOLVE_SCRIPT_API")
    if env_dir:
        dirs.append(Path(env_dir) / "Modules")
    for path in _DEFAULT_MODULE_PATHS.get(sys.platform, _DEFAULT_MODULE_PATHS["linux"]):
        dirs.append(Path(path))
    return [d for d in dirs if d.exists()]


def _import_scripting_module() -> Any:
    """Import ``DaVinciResolveScript``, extending sys.path if necessary."""
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError:
        pass

    for module_dir in _candidate_module_dirs():
        if str(module_dir) not in sys.path:
            sys.path.append(str(module_dir))
    try:
        return importlib.import_module("DaVinciResolveScript")
    except ImportError as exc:
        raise ResolveConnectionError(
            "Could not import 'DaVinciResolveScript'. Make sure DaVinci Resolve "
            "Studio is installed and the scripting environment variables are set "
            "(RESOLVE_SCRIPT_API / PYTHONPATH). See docs/INSTALL.md."
        ) from exc


def get_resolve(injected: Optional[Any] = None) -> Any:
    """Return a connected Resolve application object.

    Args:
        injected: When running inside Resolve, pass the auto-injected ``resolve``
            object (or the ``bmd``/``fusion`` globals) to skip module discovery.

    Returns:
        The Resolve application object.

    Raises:
        ResolveConnectionError: If Resolve is not running or cannot be reached.
    """
    if injected is not None:
        return injected

    # When executed by Resolve's own interpreter, a global ``resolve`` may exist.
    global_resolve = globals().get("resolve")
    if global_resolve is not None:
        return global_resolve

    module = _import_scripting_module()
    try:
        resolve = module.scriptapp("Resolve")
    except Exception as exc:  # noqa: BLE001 - normalise to our error type
        raise ResolveConnectionError(f"scriptapp('Resolve') failed: {exc}") from exc

    if resolve is None:
        raise ResolveConnectionError(
            "DaVinci Resolve is not running or scripting is disabled. Open Resolve "
            "Studio and enable Preferences ▸ System ▸ General ▸ External scripting."
        )
    _log.info("Connected to DaVinci Resolve.")
    return resolve
