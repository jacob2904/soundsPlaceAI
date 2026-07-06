"""Integration test for SceneAgent using a generated test video.

Requires ffmpeg (used to synthesise a short clip). Skipped automatically if
ffmpeg is not available so the rest of the suite still runs.
"""

import shutil
import subprocess

import pytest

from cinesfx.analysis.scene_agent import SceneAgent
from cinesfx.models import ClipSelection

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


def _make_video(path, seconds=2):
    """Create a tiny solid-colour test video with ffmpeg."""
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={seconds}:size=320x240:rate=24",
            "-y",
            str(path),
        ],
        check=True,
    )


def test_scene_agent_extracts_keyframes(tmp_path):
    video = tmp_path / "clip.mp4"
    _make_video(video, seconds=2)

    clip = ClipSelection(
        item_id="c1",
        name="test",
        source_path=str(video),
        timeline_start_frame=0,
        timeline_end_frame=48,
        source_start_seconds=0.0,
        source_end_seconds=2.0,
        fps=24.0,
    )
    agent = SceneAgent(
        {"frames_per_scene": 2, "keyframe_width": 160, "min_scene_seconds": 0.2},
        cache_dir=tmp_path / "cache",
    )
    scenes = agent.analyze(clip)
    assert scenes, "expected at least one scene"
    for scene in scenes:
        assert scene.keyframes
        for keyframe in scene.keyframes:
            assert keyframe.image_path.exists()
            assert keyframe.image_path.stat().st_size > 0


def test_bound_scene_count_merges_when_too_many(tmp_path):
    # This logic is pure (no ffmpeg): 1000 shots must collapse to max_scenes,
    # while still spanning the whole clip (first start .. last end preserved).
    agent = SceneAgent({"max_scenes": 50}, cache_dir=tmp_path / "cache")
    boundaries = [(float(i), float(i) + 1.0) for i in range(1000)]
    merged = agent._bound_scene_count(boundaries)
    assert len(merged) == 50
    assert merged[0][0] == 0.0            # first shot's start preserved
    assert merged[-1][1] == 1000.0        # last shot's end preserved
    # Coverage is monotonic and contiguous across the merged scenes.
    for earlier, later in zip(merged, merged[1:]):
        assert later[0] >= earlier[0]


def test_bound_scene_count_keeps_small_lists(tmp_path):
    agent = SceneAgent({"max_scenes": 400}, cache_dir=tmp_path / "cache")
    boundaries = [(0.0, 1.0), (1.0, 2.0)]
    assert agent._bound_scene_count(boundaries) == boundaries


def test_resolve_frame_skip_auto_scales_with_length(tmp_path):
    agent = SceneAgent(
        {"frame_skip": -1, "long_clip_threshold_seconds": 600, "target_eval_fps": 4.0},
        cache_dir=tmp_path / "cache",
    )
    # Short clip -> frame-accurate (no skipping).
    assert agent._resolve_frame_skip(duration_seconds=30.0, fps=24.0) == 0
    # Long clip at 24fps targeting ~4fps -> skip 5 (evaluate every 6th frame).
    assert agent._resolve_frame_skip(duration_seconds=3600.0, fps=24.0) == 5


def test_scene_agent_uses_cache(tmp_path):
    video = tmp_path / "clip.mp4"
    _make_video(video, seconds=1)
    clip = ClipSelection(
        item_id="c1",
        name="test",
        source_path=str(video),
        timeline_start_frame=0,
        timeline_end_frame=24,
        source_start_seconds=0.0,
        source_end_seconds=1.0,
        fps=24.0,
    )
    agent = SceneAgent({"frames_per_scene": 1}, cache_dir=tmp_path / "cache")
    first = agent.analyze(clip)
    second = agent.analyze(clip)  # should hit cache, identical result
    assert len(first) == len(second)
