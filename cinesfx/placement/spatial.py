"""Realistic (Soundly-style) spatialisation math.

Converts a cue's abstract ``distance`` (0 close .. 1 far) and ``pan`` (-1..+1)
hints into concrete gain attenuation and a clamped pan value, so placed effects
sit believably in the scene rather than sounding flat and centred.

Pure functions only — trivially unit-testable, no Resolve or audio deps.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpatialSettings:
    """Tunable spatialisation parameters (from config ``spatial`` section)."""

    enabled: bool = True
    max_distance_attenuation_db: float = -12.0
    max_pan: float = 0.8


@dataclass(frozen=True)
class SpatialResult:
    """The computed gain offset and clamped pan for a sound."""

    gain_offset_db: float
    pan: float


def compute_spatial(
    distance: float, pan: float, settings: SpatialSettings
) -> SpatialResult:
    """Return gain/pan adjustments for a sound at a given distance and pan.

    Args:
        distance: Perceived distance, 0 (close) .. 1 (far).
        pan: Requested pan, -1 (hard left) .. +1 (hard right).
        settings: Spatialisation configuration.

    Returns:
        A :class:`SpatialResult` with a gain offset (dB, <= 0) and clamped pan.
    """
    clamped_distance = _clamp(distance, 0.0, 1.0)
    requested_pan = _clamp(pan, -1.0, 1.0)

    if not settings.enabled:
        return SpatialResult(gain_offset_db=0.0, pan=requested_pan)

    # Farther sounds are quieter; linear map keeps it predictable and gentle.
    gain_offset = clamped_distance * settings.max_distance_attenuation_db

    # Distant sources feel less directional, so shrink pan toward centre as
    # distance grows, then clamp to the configured maximum.
    directionality = 1.0 - 0.5 * clamped_distance
    pan_value = requested_pan * directionality
    pan_value = _clamp(pan_value, -settings.max_pan, settings.max_pan)

    return SpatialResult(gain_offset_db=round(gain_offset, 2), pan=round(pan_value, 3))


def seconds_to_frames(seconds: float, fps: float) -> int:
    """Convert a duration/offset in seconds to a whole number of frames."""
    if fps <= 0:
        return 0
    return int(round(seconds * fps))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
