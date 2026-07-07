"""Runtime path bootstrap for the installed CineSFX panel.

The one-click installers (.dmg / .exe) drop a **self-contained** plugin folder
into Resolve's "Workflow Integration Plugins" directory::

    com.soundsplaceai.cinesfx/
        CineSFX.py            # the panel (imports this module first)
        cinesfx_bootstrap.py  # <- this file
        cinesfx/              # the engine package
        libs/                 # bundled Python dependencies (site-packages)
        ffmpeg/ (or ffmpeg/bin)  # bundled FFmpeg binaries (optional)

So the panel works **out of the box** — no `CINESFX_HOME`, no `pip install`, no
FFmpeg on PATH — this module wires up `sys.path` and `PATH` from whatever the
installer bundled. It also keeps working from a plain dev checkout (where the
engine lives two levels up and dependencies come from the user's own Python).

Deliberately dependency-free (standard library only) so it can run *before* any
third-party import — which is the whole point.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def package_root(plugin_dir: str | Path, env: dict[str, str] | None = None) -> Path | None:
    """Return the directory to add to ``sys.path`` so ``import cinesfx`` works.

    Checks, in order: the ``CINESFX_HOME`` override, the plugin folder itself
    (installed layout, where ``cinesfx/`` sits next to the script), and the repo
    root two levels up (dev checkout). Returns ``None`` if none contains the
    package.
    """
    env = os.environ if env is None else env
    plugin_path = Path(plugin_dir)
    candidates: list[Path] = []
    home = (env.get("CINESFX_HOME") or "").strip()
    if home:
        candidates.append(Path(home))
    candidates.append(plugin_path)          # installed: cinesfx/ sits alongside
    candidates.append(plugin_path.parent)   # dev checkout: repo root is one up
    for candidate in candidates:
        if (candidate / "cinesfx" / "__init__.py").is_file():
            return candidate
    return None


def libs_dir(plugin_dir: str | Path) -> Path | None:
    """Return the bundled dependencies folder (``libs/``) if it exists."""
    path = Path(plugin_dir) / "libs"
    return path if path.is_dir() else None


def ffmpeg_dirs(plugin_dir: str | Path) -> list[Path]:
    """Return any bundled FFmpeg binary folders (``ffmpeg/`` or ``ffmpeg/bin``)."""
    base = Path(plugin_dir)
    found: list[Path] = []
    for name in ("ffmpeg", os.path.join("ffmpeg", "bin")):
        candidate = base / name
        if candidate.is_dir():
            found.append(candidate)
    return found


def apply(
    plugin_dir: str | Path,
    env: dict[str, str] | None = None,
    sys_path: list[str] | None = None,
) -> Path | None:
    """Wire up ``sys.path`` + ``PATH`` from the (possibly bundled) plugin folder.

    Args:
        plugin_dir: The folder containing ``CineSFX.py``.
        env: Environment mapping to update (defaults to ``os.environ``).
        sys_path: Path list to prepend to (defaults to ``sys.path``).

    Returns:
        The resolved package root (or ``None`` if the engine could not be found).
    """
    env = os.environ if env is None else env
    sys_path = sys.path if sys_path is None else sys_path

    # Bundled dependencies first, so they win over anything else installed.
    libs = libs_dir(plugin_dir)
    if libs is not None and str(libs) not in sys_path:
        sys_path.insert(0, str(libs))

    root = package_root(plugin_dir, env)
    if root is not None and str(root) not in sys_path:
        sys_path.insert(0, str(root))

    ffmpeg_folders = ffmpeg_dirs(plugin_dir)
    if ffmpeg_folders:
        current = env.get("PATH", "")
        additions = os.pathsep.join(str(folder) for folder in ffmpeg_folders)
        env["PATH"] = additions + (os.pathsep + current if current else "")

    return root
