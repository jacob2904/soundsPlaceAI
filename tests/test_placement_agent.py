"""Tests for the PlacementAgent's timing / lane / gain logic."""

from pathlib import Path

from cinesfx.models import ClipSelection, Keyframe, Scene, SfxCue, SfxKind, SoundAsset
from cinesfx.placement.placement_agent import PlacementAgent


def _clip() -> ClipSelection:
    return ClipSelection(
        item_id="c1",
        name="shot",
        source_path="/tmp/a.mov",
        timeline_start_frame=1000,
        timeline_end_frame=1000 + 240,  # 10s at 24fps
        source_start_seconds=0.0,
        source_end_seconds=10.0,
        fps=24.0,
    )


def _scene() -> Scene:
    return Scene(0, 0.0, 10.0, (Keyframe(Path("/tmp/x.jpg"), 5.0),))


def _asset() -> SoundAsset:
    return SoundAsset(provider="test", asset_id="a", title="a", duration_seconds=1.0)


def _agent() -> PlacementAgent:
    placement_cfg = {
        "max_lanes": 2,
        "default_fade_ms": 40,
        "headroom_db": -3.0,
        "ambience_gain_db": -18.0,
    }
    spatial_cfg = {"enabled": True, "max_distance_attenuation_db": -12.0, "max_pan": 0.8}
    return PlacementAgent(placement_cfg, spatial_cfg)


def test_onset_maps_to_absolute_record_frame():
    cue = SfxCue(description="d", query="q", onset_seconds=2.0, scene_index=0)
    plan = _agent().plan_for_clip(_clip(), [_scene()], [(cue, _asset(), Path("/tmp/a.mp3"))])
    assert plan.count == 1
    # 1000 + 2.0s * 24fps = 1048
    assert plan.placements[0].record_frame == 1048


def test_overlapping_cues_use_separate_lanes():
    cues = [
        (SfxCue(description="a", query="a", onset_seconds=1.0, scene_index=0),
         _asset(), Path("/tmp/a.mp3")),
        (SfxCue(description="b", query="b", onset_seconds=1.0, scene_index=0),
         _asset(), Path("/tmp/b.mp3")),
    ]
    plan = _agent().plan_for_clip(_clip(), [_scene()], cues)
    lanes = {p.track_lane for p in plan.placements}
    assert lanes == {0, 1}


def test_too_many_overlaps_produce_warning():
    cues = [
        (SfxCue(description=str(i), query=str(i), onset_seconds=1.0, scene_index=0),
         _asset(), Path("/tmp/a.mp3"))
        for i in range(3)  # only 2 lanes configured
    ]
    plan = _agent().plan_for_clip(_clip(), [_scene()], cues)
    assert plan.count == 2
    assert len(plan.warnings) == 1


def test_ambience_gain_is_lowered():
    cue = SfxCue(
        description="wind",
        query="wind",
        kind=SfxKind.AMBIENCE,
        gain_db=0.0,
        scene_index=0,
    )
    plan = _agent().plan_for_clip(_clip(), [_scene()], [(cue, _asset(), Path("/tmp/a.mp3"))])
    # ambience clamps to <= -18 dB, then spatial offset (0 here) applies.
    assert plan.placements[0].gain_db <= -18.0


def test_onset_clamped_into_scene_window():
    scene = Scene(0, 3.0, 6.0, (Keyframe(Path("/tmp/x.jpg"), 4.0),))
    cue = SfxCue(description="d", query="q", onset_seconds=0.0, scene_index=0)
    plan = _agent().plan_for_clip(_clip(), [scene], [(cue, _asset(), Path("/tmp/a.mp3"))])
    # onset 0 is before the scene start (3s) -> clamped to 3s -> 1000 + 72 = 1072
    assert plan.placements[0].record_frame == 1072
