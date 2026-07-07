"""AudioRenderer — actually apply gain, pan, and fades to each SFX.

DaVinci Resolve's scripting API does not expose per-clip audio gain / pan / fade
controls, so instead of only *annotating* the intended values (as a marker), this
renderer **bakes them into the audio file** with FFmpeg before the clip is imported
and placed. The processed file is:

  * gain-adjusted     (``volume=<gain>dB`` — includes spatial distance attenuation),
  * positioned        (constant-power stereo pan from the cue's on-screen position),
  * faded             (``afade`` in/out), and
  * trimmed to the exact placed length so the baked fade-out lands on the clip's end.

The result is a stereo file that sounds correct in the final render on any machine,
with no dependence on the Resolve audio API. Everything is content-addressed and
cached, and if FFmpeg is unavailable the renderer transparently falls back to the
original file (the marker annotation still records the intended values).
"""

from __future__ import annotations

import hashlib
import math
import shutil
import subprocess
from pathlib import Path
from typing import Any

from cinesfx.logging_utils import get_logger
from cinesfx.models import PlannedPlacement

_log = get_logger("audio.render")


def pan_gains(pan: float) -> tuple[float, float]:
    """Return constant-power (left, right) gains for ``pan`` in [-1, 1].

    -1 = hard left, 0 = centre (~-3 dB per side, equal power), +1 = hard right.
    """
    clamped = max(-1.0, min(1.0, pan))
    angle = (clamped + 1.0) * (math.pi / 4.0)  # 0 .. pi/2
    return math.cos(angle), math.sin(angle)


def build_filter_chain(
    gain_db: float,
    pan: float,
    fade_in_seconds: float,
    fade_out_seconds: float,
    duration_seconds: float,
) -> str:
    """Build the FFmpeg ``-af`` chain that bakes gain, pan, and fades.

    Args:
        gain_db: Loudness change in dB (already includes distance attenuation).
        pan: Stereo position, -1 (left) .. +1 (right).
        fade_in_seconds: Fade-in length (<=0 disables).
        fade_out_seconds: Fade-out length (<=0 or unknown duration disables).
        duration_seconds: Final clip length; needed to time the fade-out.

    Returns:
        A comma-separated FFmpeg audio filter string.
    """
    left, right = pan_gains(pan)
    filters = [
        # Downmix any input (mono/stereo/…) to mono so panning is predictable.
        "aformat=channel_layouts=mono",
        f"volume={gain_db:.2f}dB",
        f"pan=stereo|c0={left:.4f}*c0|c1={right:.4f}*c0",
    ]
    if fade_in_seconds > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in_seconds:.3f}")
    if fade_out_seconds > 0 and duration_seconds > 0:
        out_start = max(0.0, duration_seconds - fade_out_seconds)
        filters.append(f"afade=t=out:st={out_start:.3f}:d={fade_out_seconds:.3f}")
    return ",".join(filters)


class AudioRenderer:
    """Bake gain/pan/fades into SFX files via FFmpeg, with caching + fallback."""

    def __init__(
        self,
        placement_cfg: dict[str, Any],
        cache_dir: Path,
        enabled: bool = True,
    ) -> None:
        self._enabled = bool(enabled)
        self._format = str(placement_cfg.get("render_format", "wav")).lower().lstrip(".")
        self._dir = Path(cache_dir) / "rendered"
        self._ffmpeg = shutil.which("ffmpeg")
        self._warned = False

    @property
    def available(self) -> bool:
        """True when processing can actually run (enabled + FFmpeg present)."""
        return self._enabled and self._ffmpeg is not None

    def render(self, placement: PlannedPlacement, fps: float) -> Path:
        """Return a processed audio file for ``placement`` (or the original).

        Never raises: on any problem it logs and returns the untouched source
        file, so placement continues with the marker annotation as before.
        """
        source = Path(placement.audio_file)
        if not self.available:
            if self._enabled and not self._warned:
                self._warned = True
                _log.warning(
                    "FFmpeg not found; placing SFX without baked gain/pan/fades "
                    "(the intended values are still recorded as clip markers)."
                )
            return source
        if not source.exists():
            return source
        try:
            return self._render(placement, source, fps)
        except Exception as exc:  # noqa: BLE001 - fx are best-effort, never fatal
            _log.warning("Audio fx render failed for %s: %s", source.name, exc)
            return source

    # ------------------------------------------------------------------ internals

    def _render(self, placement: PlannedPlacement, source: Path, fps: float) -> Path:
        rate = fps or placement.clip.fps or 24.0
        fade_in = max(0, placement.fade_in_frames) / rate
        fade_out = max(0, placement.fade_out_frames) / rate
        duration = placement.duration_frames / rate if placement.duration_frames > 0 else 0.0

        chain = build_filter_chain(
            placement.gain_db, placement.pan, fade_in, fade_out, duration
        )
        out_path = self._output_path(source, placement, duration, chain)
        if out_path.exists():
            return out_path

        out_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            self._ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
        ]
        if duration > 0:
            command += ["-t", f"{duration:.3f}"]
        command += ["-af", chain, "-y", str(out_path)]

        subprocess.run(command, capture_output=True, text=True, check=True)
        if not out_path.exists():
            raise RuntimeError("FFmpeg reported success but wrote no output file.")
        return out_path

    def _output_path(
        self,
        source: Path,
        placement: PlannedPlacement,
        duration: float,
        chain: str,
    ) -> Path:
        """Return a content-addressed output path (cache key covers all inputs)."""
        try:
            stat = source.stat()
            identity = f"{source}:{stat.st_size}:{int(stat.st_mtime)}"
        except OSError:
            identity = str(source)
        key = "|".join(
            [
                identity,
                f"{placement.gain_db:.2f}",
                f"{placement.pan:.4f}",
                str(placement.fade_in_frames),
                str(placement.fade_out_frames),
                f"{duration:.3f}",
                chain,
                self._format,
            ]
        )
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self._dir / f"cinesfx_{digest}.{self._format}"
