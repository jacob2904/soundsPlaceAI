"""Tests for baking gain/pan/fades into SFX with the AudioRenderer."""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from cinesfx.audio.render import AudioRenderer, build_filter_chain, pan_gains
from cinesfx.models import ClipSelection, PlannedPlacement, SfxCue, SoundAsset

_FFMPEG = shutil.which("ffmpeg")
_FFPROBE = shutil.which("ffprobe")


def _placement(
    audio_file: Path,
    *,
    gain_db: float = -6.0,
    pan: float = 0.0,
    fade_in_frames: int = 6,
    fade_out_frames: int = 6,
    duration_frames: int = 24,
) -> PlannedPlacement:
    clip = ClipSelection(
        item_id="1", name="clip", source_path="/tmp/v.mov",
        timeline_start_frame=0, timeline_end_frame=120,
        source_start_seconds=0.0, source_end_seconds=5.0, fps=24.0,
    )
    cue = SfxCue(description="door", query="door")
    asset = SoundAsset(provider="local", asset_id="a", title="door", duration_seconds=3.0)
    return PlannedPlacement(
        clip=clip, cue=cue, asset=asset, audio_file=audio_file,
        record_frame=0, track_lane=0, gain_db=gain_db, pan=pan,
        fade_in_frames=fade_in_frames, fade_out_frames=fade_out_frames,
        duration_frames=duration_frames,
    )


# ------------------------------------------------------------------- pure logic


def test_pan_gains_are_constant_power():
    left, right = pan_gains(-1.0)
    assert left == pytest.approx(1.0, abs=1e-6)
    assert right == pytest.approx(0.0, abs=1e-6)

    left, right = pan_gains(1.0)
    assert left == pytest.approx(0.0, abs=1e-6)
    assert right == pytest.approx(1.0, abs=1e-6)

    left, right = pan_gains(0.0)
    assert left == pytest.approx(right)
    assert left == pytest.approx(math.sqrt(0.5), abs=1e-6)  # equal power centre


def test_filter_chain_includes_gain_pan_and_fades():
    chain = build_filter_chain(-6.0, 1.0, 0.25, 0.25, 1.0)
    assert "volume=-6.00dB" in chain
    assert "pan=stereo" in chain
    assert "afade=t=in:st=0:d=0.250" in chain
    assert "afade=t=out:st=0.750:d=0.250" in chain


def test_filter_chain_skips_fade_out_when_duration_unknown():
    chain = build_filter_chain(0.0, 0.0, 0.1, 0.1, 0.0)
    assert "afade=t=in" in chain
    assert "afade=t=out" not in chain  # can't time a fade-out without a length


# ---------------------------------------------------------------- fallbacks


def test_render_returns_original_when_disabled(tmp_path):
    src = tmp_path / "s.wav"
    src.write_bytes(b"x")
    renderer = AudioRenderer({}, tmp_path / "cache", enabled=False)
    assert renderer.available is False
    assert renderer.render(_placement(src), 24.0) == src


def test_render_returns_original_when_ffmpeg_missing(tmp_path):
    src = tmp_path / "s.wav"
    src.write_bytes(b"x")
    renderer = AudioRenderer({}, tmp_path / "cache", enabled=True)
    renderer._ffmpeg = None  # simulate FFmpeg not installed
    assert renderer.available is False
    assert renderer.render(_placement(src), 24.0) == src


# ------------------------------------------------------------ real FFmpeg render


@pytest.mark.skipif(not (_FFMPEG and _FFPROBE), reason="FFmpeg/ffprobe not installed")
def test_render_bakes_stereo_and_trims_and_caches(tmp_path):
    src = tmp_path / "tone.wav"
    subprocess.run(
        [_FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
         "-i", "sine=frequency=440:duration=3", "-ac", "1", "-y", str(src)],
        check=True,
    )

    renderer = AudioRenderer({"render_format": "wav"}, tmp_path / "cache", enabled=True)
    placement = _placement(src, pan=1.0, duration_frames=24)  # 24f @ 24fps = 1.0s
    out = renderer.render(placement, 24.0)

    assert out != src and out.exists()
    info = json.loads(subprocess.run(
        [_FFPROBE, "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(out)],
        capture_output=True, text=True, check=True,
    ).stdout)
    stream = info["streams"][0]
    assert int(stream["channels"]) == 2  # panned into stereo
    assert float(info["format"]["duration"]) == pytest.approx(1.0, abs=0.2)  # trimmed

    # Second call is a cache hit: same path, no re-render.
    assert renderer.render(placement, 24.0) == out
