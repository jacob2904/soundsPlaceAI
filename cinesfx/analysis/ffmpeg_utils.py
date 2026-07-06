"""Thin, dependency-light helpers around the system ``ffmpeg`` / ``ffprobe``.

Only tiny, seek-based operations are used so that even multi-hour source files are
cheap to work with: ``-ss`` is always placed *before* ``-i`` so ffmpeg seeks to the
timestamp before decoding instead of decoding from the start.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from cinesfx.logging_utils import get_logger

_log = get_logger("analysis.ffmpeg")


class FfmpegError(RuntimeError):
    """Raised when ffmpeg/ffprobe is missing or a command fails."""


def ensure_ffmpeg() -> None:
    """Verify ``ffmpeg`` and ``ffprobe`` are available on PATH.

    Raises:
        FfmpegError: If either binary cannot be found.
    """
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise FfmpegError(
                f"'{binary}' was not found on PATH. Install FFmpeg and try again."
            )


def probe_duration_seconds(video_path: Path) -> float:
    """Return the duration of ``video_path`` in seconds using ffprobe.

    Args:
        video_path: Path to the media file.

    Returns:
        Duration in seconds (0.0 if it cannot be determined).

    Raises:
        FfmpegError: If ffprobe is missing or the file cannot be read.
    """
    ensure_ffmpeg()
    if not video_path.exists():
        raise FfmpegError(f"Media file does not exist: {video_path}")

    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        str(video_path),
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, check=True
        )
        payload = json.loads(completed.stdout or "{}")
        return float(payload.get("format", {}).get("duration", 0.0) or 0.0)
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        raise FfmpegError(f"ffprobe failed for '{video_path}': {exc}") from exc


def extract_frame(
    video_path: Path,
    timestamp_seconds: float,
    output_path: Path,
    width: int = 512,
    quality: int = 3,
) -> Path:
    """Extract a single downscaled JPEG frame at ``timestamp_seconds``.

    Args:
        video_path: Source media path.
        timestamp_seconds: Seek position (absolute, within the source file).
        output_path: Where to write the JPEG.
        width: Output width in pixels; height keeps aspect ratio.
        quality: ffmpeg ``-q:v`` value (2 best .. 31 worst).

    Returns:
        ``output_path`` on success.

    Raises:
        FfmpegError: If the frame could not be produced.
    """
    ensure_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, timestamp_seconds):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        str(quality),
        "-vf",
        f"scale={width}:-2",
        "-y",
        str(output_path),
    ]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        raise FfmpegError(
            f"Could not extract frame at {timestamp_seconds:.3f}s from "
            f"'{video_path}': {exc.stderr.strip() if exc.stderr else exc}"
        ) from exc

    if not output_path.exists():
        raise FfmpegError(
            f"ffmpeg reported success but no frame was written to '{output_path}'."
        )
    return output_path
