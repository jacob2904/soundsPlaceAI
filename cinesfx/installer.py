"""Install the CineSFX panel into DaVinci Resolve — the engine behind the installers.

The one-click ``.dmg`` (macOS) and ``.exe`` (Windows) both do the same simple,
reliable thing: copy a **self-contained payload** (the panel + the ``cinesfx``
engine + bundled dependencies + FFmpeg) into Resolve's per-OS "Workflow
Integration Plugins" folder, inside ``com.soundsplaceai.cinesfx``. After that the
panel appears under *Workspace ▸ Workflow Integrations ▸ CineSFX AI* and runs out
of the box (see :mod:`cinesfx` and ``plugin/cinesfx_bootstrap.py``).

This module keeps that logic in pure, cross-platform Python so it can be unit
tested and reused by the platform installers, a GUI, or ``python -m
cinesfx.installer``.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

PLUGIN_ID = "com.soundsplaceai.cinesfx"

# (path relative to the repo root, path relative to the installed plugin folder).
# The panel script + bootstrap land at the plugin-folder root, next to the engine
# package, so ``cinesfx_bootstrap`` can wire everything up with no env vars.
PAYLOAD_MAP: tuple[tuple[str, str], ...] = (
    ("plugin/CineSFX.py", "CineSFX.py"),
    ("plugin/cinesfx_bootstrap.py", "cinesfx_bootstrap.py"),
    ("plugin/manifest.xml", "manifest.xml"),
    ("cinesfx", "cinesfx"),
    ("scripts", "scripts"),
    ("config.example.yaml", "config.example.yaml"),
)

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.tmp")


class InstallError(RuntimeError):
    """Raised when installation cannot proceed."""


@dataclass
class InstallResult:
    """Outcome of an install, safe to print to a user."""

    plugin_dir: Path
    items: list[str]

    def summary(self) -> str:
        return (
            f"Installed CineSFX to:\n  {self.plugin_dir}\n"
            f"Open DaVinci Resolve ▸ Workspace ▸ Workflow Integrations ▸ CineSFX AI."
        )


def _resolve_system(system: Optional[str]) -> str:
    return system or platform.system()


def plugins_root(system: Optional[str] = None, env: Optional[dict] = None) -> Path:
    """Return Resolve's "Workflow Integration Plugins" folder for the OS.

    ``CINESFX_PLUGINS_DIR`` overrides everything (handy for testing / custom
    installs).
    """
    env = os.environ if env is None else env
    override = (env.get("CINESFX_PLUGINS_DIR") or "").strip()
    if override:
        return Path(override)

    name = _resolve_system(system)
    if name == "Darwin":
        return Path(
            "/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
            "Workflow Integration Plugins"
        )
    if name == "Windows":
        base = env.get("PROGRAMDATA", r"C:\ProgramData")
        return (
            Path(base)
            / "Blackmagic Design"
            / "DaVinci Resolve"
            / "Support"
            / "Workflow Integration Plugins"
        )
    # Linux and anything else.
    return Path("/opt/resolve/Workflow Integration Plugins")


def plugin_dir(system: Optional[str] = None, env: Optional[dict] = None) -> Path:
    """Return the full install path (``…/Workflow Integration Plugins/<id>``)."""
    return plugins_root(system, env) / PLUGIN_ID


def repo_root() -> Path:
    """Return the repository root (the parent of the ``cinesfx`` package)."""
    return Path(__file__).resolve().parent.parent


def stage_payload(source_root: Path | str, payload_dir: Path | str) -> list[str]:
    """Assemble a runnable plugin payload under ``payload_dir`` from the repo.

    Build scripts call this, then add ``libs/`` (vendored deps) and ``ffmpeg/``
    before packing the ``.dmg`` / ``.exe``.

    Returns the list of top-level items staged.
    """
    source = Path(source_root)
    payload = Path(payload_dir)
    payload.mkdir(parents=True, exist_ok=True)

    staged: list[str] = []
    for src_rel, dest_rel in PAYLOAD_MAP:
        src = source / src_rel
        if not src.exists():
            continue
        dest = payload / dest_rel
        if src.is_dir():
            shutil.copytree(src, dest, dirs_exist_ok=True, ignore=_IGNORE)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        staged.append(dest_rel)

    if "CineSFX.py" not in staged:
        raise InstallError(
            f"Could not stage payload: '{source}' does not look like the CineSFX "
            f"repository (plugin/CineSFX.py missing)."
        )
    return staged


def install_payload(
    payload_dir: Path | str,
    system: Optional[str] = None,
    env: Optional[dict] = None,
) -> InstallResult:
    """Copy an already-staged payload into Resolve's plugin folder."""
    payload = Path(payload_dir)
    if not payload.is_dir():
        raise InstallError(f"Payload folder not found: {payload}")
    if not (payload / "CineSFX.py").is_file():
        raise InstallError(f"'{payload}' is not a CineSFX payload (no CineSFX.py).")

    dest = plugin_dir(system, env)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(payload, dest, dirs_exist_ok=True, ignore=_IGNORE)
    items = sorted(child.name for child in dest.iterdir())
    return InstallResult(plugin_dir=dest, items=items)


def install_from_repo(
    source_root: Optional[Path | str] = None,
    system: Optional[str] = None,
    env: Optional[dict] = None,
) -> InstallResult:
    """Stage the payload from a repo checkout and install it (for dev/manual use)."""
    source = Path(source_root) if source_root else repo_root()
    with tempfile.TemporaryDirectory() as tmp:
        stage_payload(source, tmp)
        return install_payload(tmp, system, env)


def uninstall(system: Optional[str] = None, env: Optional[dict] = None) -> bool:
    """Remove an installed plugin folder. Returns True if something was removed."""
    dest = plugin_dir(system, env)
    if dest.is_dir():
        shutil.rmtree(dest)
        return True
    return False


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: install (default), stage a payload, or uninstall."""
    parser = argparse.ArgumentParser(
        prog="cinesfx.installer",
        description="Install the CineSFX panel into DaVinci Resolve.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--payload", metavar="DIR",
        help="Install an already-staged payload folder (used by the .dmg/.exe).",
    )
    group.add_argument(
        "--stage-only", metavar="DIR",
        help="Only assemble the payload from this repo into DIR (build step).",
    )
    group.add_argument(
        "--uninstall", action="store_true", help="Remove an installed CineSFX plugin."
    )
    parser.add_argument(
        "--system", help="Override the OS (Darwin/Windows/Linux) for the target path."
    )
    args = parser.parse_args(argv)

    try:
        if args.uninstall:
            removed = uninstall(system=args.system)
            print("Removed CineSFX." if removed else "Nothing to remove.")
            return 0
        if args.stage_only:
            staged = stage_payload(repo_root(), args.stage_only)
            print(f"Staged payload ({len(staged)} item(s)) → {args.stage_only}")
            return 0
        if args.payload:
            result = install_payload(args.payload, system=args.system)
        else:
            result = install_from_repo(system=args.system)
        print(result.summary())
        return 0
    except (InstallError, OSError) as exc:
        print(f"Install failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
