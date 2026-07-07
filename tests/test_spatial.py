"""Tests for the spatialisation math."""

from cinesfx.placement.spatial import (
    SpatialSettings,
    compute_spatial,
    seconds_to_frames,
)


def test_close_centre_sound_is_unchanged():
    result = compute_spatial(distance=0.0, pan=0.0, settings=SpatialSettings())
    assert result.gain_offset_db == 0.0
    assert result.pan == 0.0


def test_far_sound_is_attenuated():
    settings = SpatialSettings(max_distance_attenuation_db=-12.0)
    result = compute_spatial(distance=1.0, pan=0.0, settings=settings)
    assert result.gain_offset_db == -12.0


def test_pan_is_clamped_to_max():
    settings = SpatialSettings(max_pan=0.8)
    result = compute_spatial(distance=0.0, pan=1.0, settings=settings)
    assert result.pan == 0.8


def test_distance_reduces_directionality():
    settings = SpatialSettings(max_pan=1.0)
    near = compute_spatial(distance=0.0, pan=1.0, settings=settings).pan
    far = compute_spatial(distance=1.0, pan=1.0, settings=settings).pan
    assert far < near


def test_disabled_spatial_passes_pan_through_without_gain():
    settings = SpatialSettings(enabled=False)
    result = compute_spatial(distance=1.0, pan=0.5, settings=settings)
    assert result.gain_offset_db == 0.0
    assert result.pan == 0.5


def test_seconds_to_frames_rounds():
    assert seconds_to_frames(1.0, 24.0) == 24
    assert seconds_to_frames(2.0, 25.0) == 50
    assert seconds_to_frames(1.0, 0.0) == 0
