"""Command-line runner for the CineSFX pipeline.

Runs against the DaVinci Resolve instance that is currently open. Use this for
scripted/batch workflows or to preview a plan without the panel UI.

Examples:
    python -m scripts.run_cli --selection --dry-run
    python -m scripts.run_cli --all
    python -m scripts.run_cli --color Orange
"""

from __future__ import annotations

import argparse
import sys

from cinesfx.config import ConfigError
from cinesfx.logging_utils import configure_logging, get_logger
from cinesfx.orchestrator import build_orchestrator
from cinesfx.resolve.timeline_agent import SELECT_ALL, SELECT_COLOR, SELECT_CURRENT

_log = get_logger("cli")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cinesfx",
        description="AI cinematic sound-effects placement for DaVinci Resolve.",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--selection",
        action="store_true",
        help="Process the current timeline item (default).",
    )
    scope.add_argument(
        "--all",
        action="store_true",
        help="Process every clip on the timeline (whole video).",
    )
    scope.add_argument(
        "--color",
        metavar="CLIP_COLOR",
        help="Process only clips tagged with this clip color (e.g. Orange).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and print SFX without modifying the timeline (free preview).",
    )
    parser.add_argument(
        "--activate",
        metavar="LICENSE_KEY",
        help="Activate a one-time lifetime license key and exit.",
    )
    parser.add_argument(
        "--license-status",
        action="store_true",
        help="Show the current license status and exit.",
    )
    parser.add_argument("--config", help="Path to config.yaml.")
    parser.add_argument("--env", help="Path to a .env file.")
    return parser.parse_args(argv)


def _mode_and_color(args: argparse.Namespace) -> tuple[str, str | None]:
    if args.all:
        return SELECT_ALL, None
    if args.color:
        return SELECT_COLOR, args.color
    return SELECT_CURRENT, None


def _handle_license_commands(args: argparse.Namespace) -> int | None:
    """Handle --activate / --license-status. Returns exit code or None."""
    from cinesfx.licensing import LicenseError
    from cinesfx.settings import activate_license, get_license_status

    if args.activate:
        try:
            status = activate_license(args.activate)
        except LicenseError as exc:
            print(f"Activation failed: {exc}")
            return 1
        print(status.message)
        return 0

    if args.license_status:
        print(get_license_status().message)
        return 0
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    configure_logging()

    license_result = _handle_license_commands(args)
    if license_result is not None:
        return license_result

    try:
        orchestrator = build_orchestrator(config_path=args.config, env_path=args.env)
    except ConfigError as exc:
        _log.error("Configuration error: %s", exc)
        return 2

    mode, color = _mode_and_color(args)
    try:
        results = orchestrator.run(
            mode=mode, color=color, dry_run=args.dry_run, progress=_log.info
        )
    except Exception as exc:  # noqa: BLE001 - present a clean message to the user
        _log.error("Run failed: %s", exc)
        return 1

    print(orchestrator.report(results))
    if args.dry_run:
        print("\n(Dry run — no changes were made to your timeline.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
