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
