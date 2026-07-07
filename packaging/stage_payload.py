"""Assemble a self-contained CineSFX plugin payload for the installers.

Produces a ``payload/`` folder containing everything the plugin needs to run out
of the box inside DaVinci Resolve:

    payload/
        CineSFX.py, cinesfx_bootstrap.py, manifest.xml
        cinesfx/            # the engine
        scripts/            # optional CLI
        config.example.yaml
        libs/               # vendored Python dependencies (pip --target)

The platform build scripts (``build_dmg.sh`` / ``build_exe.ps1``) call this, drop
FFmpeg binaries into ``payload/ffmpeg/``, and then wrap ``payload/`` in a ``.dmg``
or ``.exe``. Run directly:

    python packaging/stage_payload.py --out build/payload            # + deps
    python packaging/stage_payload.py --out build/payload --no-deps  # code only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cinesfx.installer import repo_root, stage_payload  # noqa: E402

# The default brain SDK bundled so Gemini works with just a pasted key.
DEFAULT_BRAIN_SDK = "google-generativeai"


def _vendor_dependencies(libs_dir: Path, brain_sdk: str | None) -> None:
    """pip-install runtime deps into ``libs_dir`` for the current platform."""
    libs_dir.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    packages = ["-r", str(root / "requirements.txt")]
    if brain_sdk:
        packages += [brain_sdk]
    command = [
        sys.executable, "-m", "pip", "install",
        "--target", str(libs_dir),
        "--upgrade",
        *packages,
    ]
    print(f"Vendoring dependencies into {libs_dir} …")
    subprocess.run(command, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage a CineSFX plugin payload.")
    parser.add_argument("--out", required=True, help="Output payload directory.")
    parser.add_argument(
        "--no-deps", action="store_true",
        help="Skip vendoring Python dependencies (code only).",
    )
    parser.add_argument(
        "--brain-sdk", default=DEFAULT_BRAIN_SDK,
        help=f"Brain SDK to bundle (default: {DEFAULT_BRAIN_SDK}; '' to skip).",
    )
    args = parser.parse_args(argv)

    out = Path(args.out)
    staged = stage_payload(repo_root(), out)
    print(f"Staged {len(staged)} item(s) into {out}")

    if not args.no_deps:
        _vendor_dependencies(out / "libs", args.brain_sdk or None)

    print(
        "Payload ready. Next: drop FFmpeg binaries into "
        f"'{out / 'ffmpeg'}' (optional), then run the platform build script."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
