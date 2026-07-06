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
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Run environment checks (Resolve, FFmpeg, keys, license) and exit.",
    )
    parser.add_argument(
        "--scan-library",
        action="store_true",
        help="Index your own sound library into the catalog and exit.",
    )
    parser.add_argument(
        "--library-roots",
        nargs="+",
        metavar="FOLDER",
        help="Folder(s) to scan for --scan-library (overrides config roots).",
    )
    parser.add_argument(
        "--library-stats",
        action="store_true",
        help="Show how many sounds are in your catalog (by category) and exit.",
    )
    parser.add_argument(
        "--probe-duration",
        action="store_true",
        help="Also read audio durations while scanning (needs 'tinytag').",
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


def _handle_library_commands(args: argparse.Namespace) -> int | None:
    """Handle --scan-library / --library-stats. Returns exit code or None."""
    if not (args.scan_library or args.library_stats):
        return None

    from cinesfx.config import load_config
    from cinesfx.sound.base import SoundProviderError
    from cinesfx.sound.catalog import CatalogProvider

    try:
        config = load_config(config_path=args.config, env_path=args.env)
    except ConfigError as exc:
        print(f"Configuration error: {exc}")
        return 2

    settings = dict(config.raw.get("sound_providers", {}).get("catalog", {}))
    if args.library_roots:
        settings["roots"] = args.library_roots
    if args.probe_duration:
        settings["probe_duration"] = True
    provider = CatalogProvider(settings, config.cache_dir())

    if args.scan_library:
        try:
            stats = provider.scan(progress=print)
        except SoundProviderError as exc:
            print(f"Scan failed: {exc}")
            return 1
        print(stats.summary())

    if args.library_stats:
        info = provider.catalog.stats()
        print(f"Catalog: {info['total']} sound(s) at {info['db_path']}")
        for category, count in info["by_category"].items():
            print(f"  {category:>14}: {count}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code."""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    configure_logging()

    license_result = _handle_license_commands(args)
    if license_result is not None:
        return license_result

    library_result = _handle_library_commands(args)
    if library_result is not None:
        return library_result

    if args.doctor:
        from cinesfx.config import load_config
        from cinesfx.diagnostics import run_diagnostics, summarize

        try:
            config = load_config(config_path=args.config, env_path=args.env)
        except ConfigError:
            config = None
        results = run_diagnostics(config=config)
        print(summarize(results))
        return 0 if all(result.ok for result in results) else 1

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
