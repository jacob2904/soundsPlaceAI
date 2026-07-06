"""Tests for the shared data model."""

from cinesfx.models import ClipSelection, Keyframe, Scene, SfxCue, SfxKind
from pathlib import Path


def _clip(**overrides) -> ClipSelection:
    base = dict(
        item_id="id1",
        name="shot",
        source_path="/tmp/a.mov",
        timeline_start_frame=100,
        timeline_end_frame=340,
        source_start_seconds=2.0,
        source_end_seconds=12.0,
        fps=24.0,
    )
    base.update(overrides)
    return ClipSelection(**base)


def test_clip_duration_seconds():
    assert _clip().duration_seconds == 10.0


def test_clip_duration_never_negative():
    assert _clip(source_start_seconds=5.0, source_end_seconds=1.0).duration_seconds == 0.0


def test_scene_duration():
    scene = Scene(
        index=0,
        start_seconds=1.0,
        end_seconds=4.5,
        keyframes=(Keyframe(Path("/tmp/x.jpg"), 2.0),),
    )
    assert scene.duration_seconds == 3.5


def test_sfxcue_defaults():
    cue = SfxCue(description="door", query="door creak")
    assert cue.kind is SfxKind.SPOT
    assert cue.diegetic is True
    assert cue.confidence == 0.5
