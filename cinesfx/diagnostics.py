"""Lightweight self-checks for the CineSFX environment.

Powers the panel's "Test connection" button (and can be reused by a CLI doctor).
Each check is defensive and never raises: it returns a pass/fail result with a
short, actionable message so the user can fix issues on their own machine.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger

_log = get_logger("diagnostics")

# Which secret each brain needs, for a presence check (no network call).
_BRAIN_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

# Cloud sound providers and the secret each needs (simple single-key check).
_SOUND_ENV = {
    "epidemic": "EPIDEMIC_API_KEY",
    "freesound": "FREESOUND_API_KEY",
    "audiio": "AUDIIO_API_TOKEN",
    "musicbed": "MUSICBED_API_TOKEN",
}
# Folder-based providers that need a local library path instead of a key.
_SOUND_LOCAL = ("soundly", "local", "splice")


@dataclass(frozen=True)
class CheckResult:
    """The outcome of a single diagnostic check."""

    label: str
    ok: bool
    detail: str

    def as_line(self) -> str:
        """Return a one-line, glyph-prefixed summary for display."""
        marker = "\u2713" if self.ok else "\u2717"  # check / cross
        return f"{marker}  {self.label}: {self.detail}"


def _safe(obj: Any, method: str, *args: Any) -> Any:
    """Call ``obj.method(*args)`` if present, returning None on any failure."""
    if obj is None:
        return None
    func = getattr(obj, method, None)
    if func is None:
        return None
    try:
        return func(*args)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never raise
        _log.debug("diagnostic call %s failed: %s", method, exc)
        return None


def check_ffmpeg() -> CheckResult:
    """Verify FFmpeg/ffprobe are installed and on PATH."""
    from cinesfx.analysis.ffmpeg_utils import FfmpegError, ensure_ffmpeg

    try:
        ensure_ffmpeg()
        return CheckResult("FFmpeg", True, "found on PATH")
    except FfmpegError as exc:
        return CheckResult("FFmpeg", False, str(exc))


def check_resolve(resolve_obj: Optional[Any] = None) -> list[CheckResult]:
    """Check Resolve connectivity, current project, timeline, and clip count."""
    from cinesfx.resolve.connection import ResolveConnectionError, get_resolve

    try:
        resolve = get_resolve(resolve_obj)
    except ResolveConnectionError as exc:
        return [CheckResult("DaVinci Resolve", False, str(exc))]

    results = [CheckResult("DaVinci Resolve", True, "connected")]

    manager = _safe(resolve, "GetProjectManager")
    project = _safe(manager, "GetCurrentProject") if manager else None
    if project is None:
        results.append(CheckResult("Project", False, "no project open in Resolve"))
        return results
    results.append(
        CheckResult("Project", True, str(_safe(project, "GetName") or "open"))
    )

    timeline = _safe(project, "GetCurrentTimeline")
    if timeline is None:
        results.append(CheckResult("Timeline", False, "no timeline open"))
        return results
    results.append(
        CheckResult("Timeline", True, str(_safe(timeline, "GetName") or "open"))
    )

    clip_count = _count_video_clips(timeline)
    results.append(
        CheckResult(
            "Clips on timeline",
            clip_count > 0,
            f"{clip_count} video clip(s) found"
            if clip_count > 0
            else "no clips detected (add media to the timeline)",
        )
    )
    return results


def _count_video_clips(timeline: Any) -> int:
    """Best-effort count of video timeline items across all video tracks."""
    total = 0
    track_count = int(_safe(timeline, "GetTrackCount", "video") or 0)
    for index in range(1, track_count + 1):
        items = _safe(timeline, "GetItemListInTrack", "video", index)
        if items:
            total += len(items)
    return total


def check_brain(config: AppConfig) -> CheckResult:
    """Check that the selected brain has its API key configured."""
    brain = config.brain
    env_key = _BRAIN_ENV.get(brain)
    if not env_key:
        return CheckResult(f"Brain ({brain})", False, "unknown brain provider")
    if AppConfig.secret(env_key):
        return CheckResult(f"Brain ({brain})", True, f"{env_key} is set")
    return CheckResult(
        f"Brain ({brain})", False, f"{env_key} is not set (add it to .env)"
    )


def check_sound(config: AppConfig) -> CheckResult:
    """Check that the selected sound provider is ready (key or library path)."""
    provider = config.sound_provider

    if provider == "artlist":
        has_id = AppConfig.secret("ARTLIST_CLIENT_ID")
        has_secret = AppConfig.secret("ARTLIST_CLIENT_SECRET")
        if has_id and has_secret:
            return CheckResult("Sounds (artlist)", True, "OAuth credentials set")
        return CheckResult(
            "Sounds (artlist)",
            False,
            "set ARTLIST_CLIENT_ID and ARTLIST_CLIENT_SECRET (music only; SFX not "
            "yet exposed by Artlist's API)",
        )

    if provider == "splice":
        from cinesfx.sound.splice import resolve_splice_library

        try:
            library = resolve_splice_library(config.library_path() and str(config.library_path()))
            return CheckResult("Sounds (splice)", True, f"library: {library}")
        except Exception as exc:  # noqa: BLE001 - report, never raise
            return CheckResult("Sounds (splice)", False, str(exc))

    if provider == "catalog":
        return _check_catalog(config)

    if provider in _SOUND_LOCAL:
        library = config.library_path()
        if library and Path(library).expanduser().is_dir():
            return CheckResult(f"Sounds ({provider})", True, f"library: {library}")
        return CheckResult(
            f"Sounds ({provider})",
            False,
            "set a valid library_path (folder of audio files)",
        )

    env_key = _SOUND_ENV.get(provider)
    if not env_key:
        return CheckResult(f"Sounds ({provider})", False, "unknown sound provider")
    if AppConfig.secret(env_key):
        return CheckResult(f"Sounds ({provider})", True, f"{env_key} is set")
    return CheckResult(
        f"Sounds ({provider})", False, f"{env_key} is not set (add it to .env)"
    )


def _check_catalog(config: AppConfig) -> CheckResult:
    """Check the user's sound catalog: file populated and/or roots configured."""
    from cinesfx.library.catalog import LibraryCatalog, default_catalog_path
    from cinesfx.sound.catalog import resolve_catalog_roots

    settings = config.sound_settings()
    roots = resolve_catalog_roots(settings)
    path_setting = settings.get("catalog_path")
    catalog_path = (
        Path(path_setting).expanduser()
        if path_setting
        else default_catalog_path(config.cache_dir())
    )
    try:
        count = LibraryCatalog(catalog_path).count() if catalog_path.exists() else 0
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return CheckResult("Sounds (catalog)", False, f"catalog error: {exc}")

    if count > 0:
        return CheckResult(
            "Sounds (catalog)", True, f"{count} sound(s) indexed at {catalog_path}"
        )
    if roots:
        return CheckResult(
            "Sounds (catalog)",
            False,
            f"{len(roots)} folder(s) configured but not scanned yet — run "
            f"'Scan library' (or --scan-library)",
        )
    return CheckResult(
        "Sounds (catalog)",
        False,
        "no library folders configured — add folders and scan your library",
    )


def check_license() -> CheckResult:
    """Report the current license activation status (never a hard failure)."""
    from cinesfx.settings import get_license_status

    status = get_license_status()
    # Not being activated is fine (Preview is free), so report it as OK-info.
    return CheckResult("License", True, status.message)


def run_diagnostics(
    config: Optional[AppConfig] = None, resolve_obj: Optional[Any] = None
) -> list[CheckResult]:
    """Run every check and return the results in display order.

    Args:
        config: Loaded app config. If None, it is loaded on demand; a config
            error is reported as failed checks rather than raising.
        resolve_obj: The Resolve object injected by the panel (or None for CLI).

    Returns:
        An ordered list of :class:`CheckResult`.
    """
    results: list[CheckResult] = [check_ffmpeg()]
    results.extend(check_resolve(resolve_obj))

    if config is None:
        try:
            from cinesfx.config import load_config

            config = load_config()
        except Exception as exc:  # noqa: BLE001 - surface as a check, not a crash
            results.append(CheckResult("Configuration", False, str(exc)))
            return results

    results.append(check_brain(config))
    results.append(check_sound(config))
    results.append(check_license())
    return results


def summarize(results: list[CheckResult]) -> str:
    """Return a multi-line, human-readable report of all checks."""
    passed = sum(1 for result in results if result.ok)
    lines = [result.as_line() for result in results]
    lines.append("")
    lines.append(f"{passed}/{len(results)} checks passed.")
    return "\n".join(lines)
