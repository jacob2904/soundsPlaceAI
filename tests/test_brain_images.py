"""Tests for token-saving key-frame selection sent to the AI brain."""

import importlib.util
from pathlib import Path

from cinesfx.brain.base import BrainProvider, _sample_evenly
from cinesfx.models import Keyframe, Scene


def _scene(tmp_path: Path, index: int, frame_count: int) -> Scene:
    """Build a scene with ``frame_count`` real (on-disk) key-frame images."""
    frames = []
    for k in range(frame_count):
        path = tmp_path / f"s{index}_k{k}.jpg"
        path.write_bytes(b"jpeg")
        frames.append(Keyframe(image_path=path, clip_seconds=float(k)))
    return Scene(index=index, start_seconds=0.0, end_seconds=5.0, keyframes=tuple(frames))


def test_sample_evenly_caps_and_spaces():
    items = list(range(10))
    assert _sample_evenly(items, None) == items      # no cap
    assert _sample_evenly(items, 0) == items         # no cap
    assert _sample_evenly(items, 20) == items        # fewer than cap
    picked = _sample_evenly(items, 3)
    assert len(picked) == 3
    assert picked == sorted(picked)                  # order preserved
    assert picked[0] < picked[-1]                    # spread across the range


def test_collect_images_limits_per_scene(tmp_path):
    scenes = [_scene(tmp_path, 0, 3), _scene(tmp_path, 1, 3)]
    # Default behaviour keeps every extracted frame.
    assert len(BrainProvider._collect_images(scenes)) == 6
    # One image per scene = the big token saver.
    assert len(BrainProvider._collect_images(scenes, per_scene_limit=1)) == 2


def test_collect_images_caps_total(tmp_path):
    scenes = [_scene(tmp_path, i, 2) for i in range(10)]  # 20 frames total
    images = BrainProvider._collect_images(
        scenes, per_scene_limit=1, max_total=4
    )
    assert len(images) == 4
    assert all(isinstance(path, Path) for path in images)


def test_collect_images_skips_missing_files(tmp_path):
    scene = _scene(tmp_path, 0, 2)
    scene.keyframes[0].image_path.unlink()  # simulate a missing frame
    images = BrainProvider._collect_images([scene])
    assert len(images) == 1


def _load_panel_module():
    """Import the Resolve panel module by path (it isn't a package)."""
    panel_path = Path(__file__).resolve().parent.parent / "plugin" / "CineSFX.py"
    spec = importlib.util.spec_from_file_location("cinesfx_panel", panel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_append_folder_multi_and_single():
    panel = _load_panel_module()
    # Catalog (multi): appends unique folders, comma-separated.
    assert panel._append_folder("", "/a", multi=True) == "/a"
    assert panel._append_folder("/a", "/b", multi=True) == "/a, /b"
    assert panel._append_folder("/a, /b", "/a", multi=True) == "/a, /b"  # no dupes
    # Single-folder providers: the new pick replaces the old.
    assert panel._append_folder("/a", "/b", multi=False) == "/b"
    assert panel._append_folder("/a", "", multi=False) == "/a"  # empty pick = keep
