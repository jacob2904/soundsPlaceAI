"""SceneAgent — turns a clip's source file + range into LLM-ready scenes.

Efficiency is the whole point of this agent:
  * PySceneDetect runs only over the clip's in/out range, on down-scaled frames.
  * A few small key-frames per shot are extracted with seek-based ffmpeg calls.
  * Results are cached by (file content hash, range, params) so re-runs are free.

If PySceneDetect is unavailable, the agent falls back to uniform time sampling so
the pipeline still works (just with coarser shot boundaries).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from cinesfx.analysis.ffmpeg_utils import extract_frame, probe_duration_seconds
from cinesfx.logging_utils import get_logger
from cinesfx.models import ClipSelection, Keyframe, Scene

_log = get_logger("analysis.scene")


class SceneAgent:
    """Detect shots within a selected clip and extract representative frames."""

    def __init__(self, config: dict[str, Any], cache_dir: Path) -> None:
        """Create the agent.

        Args:
            config: The ``analysis`` section of the app config.
            cache_dir: Base cache directory for key-frames and metadata.
        """
        self._detector = str(config.get("detector", "content")).lower()
        self._threshold = float(config.get("threshold", 27.0))
        self._downscale = int(config.get("downscale_factor", 2))
        self._frames_per_scene = max(1, int(config.get("frames_per_scene", 2)))
        self._keyframe_width = int(config.get("keyframe_width", 512))
        self._min_scene_seconds = float(config.get("min_scene_seconds", 0.4))
        # Long-clip controls: keep whole-video coverage bounded and fast.
        self._max_scenes = int(config.get("max_scenes", 400))
        self._long_clip_threshold = float(
            config.get("long_clip_threshold_seconds", 600.0)
        )
        # frame_skip < 0 means "decide automatically from clip length".
        self._frame_skip = int(config.get("frame_skip", -1))
        self._target_eval_fps = float(config.get("target_eval_fps", 4.0))
        self._cache_dir = cache_dir / "keyframes"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, clip: ClipSelection) -> list[Scene]:
        """Return the list of scenes for ``clip``.

        Args:
            clip: The selected timeline clip to analyse.

        Returns:
            An ordered list of :class:`Scene` objects (clip-relative timings).
        """
        source = Path(clip.source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source media not found: {source}")

        cache_key = self._cache_key(clip)
        cached = self._load_cache(cache_key)
        if cached is not None:
            _log.info("Scene cache hit for %s (%d scenes)", clip.name, len(cached))
            return cached

        boundaries = self._detect_boundaries(clip)
        boundaries = self._bound_scene_count(boundaries)
        scenes = self._build_scenes(clip, boundaries, cache_key)
        self._save_cache(cache_key, scenes)
        _log.info("Analysed %s into %d scene(s)", clip.name, len(scenes))
        return scenes

    def _bound_scene_count(
        self, boundaries: list[tuple[float, float]]
    ) -> list[tuple[float, float]]:
        """Cap the number of scenes by merging adjacent shots evenly.

        On a long video with hundreds of cuts we still want full coverage, but we
        must keep the key-frame + brain workload bounded. If there are more shots
        than ``max_scenes``, consecutive shots are grouped into ``max_scenes``
        evenly-sized "super-scenes" that together still span the whole clip.
        """
        count = len(boundaries)
        if count <= self._max_scenes:
            return boundaries

        _log.info(
            "Merging %d shots into %d scenes for efficient coverage.",
            count,
            self._max_scenes,
        )
        merged: list[tuple[float, float]] = []
        for bucket in range(self._max_scenes):
            start_idx = bucket * count // self._max_scenes
            end_idx = ((bucket + 1) * count // self._max_scenes) - 1
            end_idx = max(start_idx, min(end_idx, count - 1))
            merged.append((boundaries[start_idx][0], boundaries[end_idx][1]))
        return merged

    # ------------------------------------------------------------------ detection

    def _detect_boundaries(self, clip: ClipSelection) -> list[tuple[float, float]]:
        """Return (start, end) second pairs relative to the clip's in-point."""
        try:
            return self._detect_with_scenedetect(clip)
        except Exception as exc:  # noqa: BLE001 - fall back, never crash pipeline
            _log.warning(
                "PySceneDetect unavailable/failed (%s); using uniform sampling.", exc
            )
            return self._uniform_boundaries(clip)

    def _detect_with_scenedetect(
        self, clip: ClipSelection
    ) -> list[tuple[float, float]]:
        """Run PySceneDetect over only the clip's range, on down-scaled frames.

        For long clips this applies frame-skipping and down-scaling so detection
        stays fast (seconds, not minutes) while still finding real cuts.
        """
        from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video

        video = open_video(clip.source_path)
        scene_manager = SceneManager()
        self._apply_downscale(scene_manager)
        detector = (
            AdaptiveDetector()
            if self._detector == "adaptive"
            else ContentDetector(threshold=self._threshold)
        )
        scene_manager.add_detector(detector)

        # Restrict detection to the clip's in/out range for efficiency.
        base_rate = video.frame_rate or clip.fps
        start_tc = clip.source_start_seconds
        end_tc = clip.source_end_seconds
        duration = max(0.0, end_tc - start_tc)
        frame_skip = self._resolve_frame_skip(duration, base_rate)
        video.seek(start_tc)
        scene_manager.detect_scenes(
            video=video,
            duration=self._as_timecode(base_rate, duration),
            frame_skip=frame_skip,
            show_progress=False,
        )
        raw = scene_manager.get_scene_list()

        boundaries: list[tuple[float, float]] = []
        for start, end in raw:
            rel_start = max(0.0, start.get_seconds() - start_tc)
            rel_end = max(rel_start, end.get_seconds() - start_tc)
            if rel_end - rel_start >= self._min_scene_seconds:
                boundaries.append((rel_start, rel_end))

        if not boundaries:
            return self._uniform_boundaries(clip)
        return boundaries

    @staticmethod
    def _as_timecode(frame_rate: float, seconds: float):
        """Build a FrameTimecode-compatible value for a duration in seconds."""
        from scenedetect import FrameTimecode

        return FrameTimecode(max(0.0, seconds), fps=frame_rate)

    def _apply_downscale(self, scene_manager: Any) -> None:
        """Configure detection down-scaling on the SceneManager, if supported."""
        try:
            if self._downscale and self._downscale > 1:
                scene_manager.auto_downscale = False
                scene_manager.downscale = self._downscale
            else:
                scene_manager.auto_downscale = True
        except (AttributeError, ValueError) as exc:
            _log.debug("Could not set downscale on SceneManager: %s", exc)

    def _resolve_frame_skip(self, duration_seconds: float, fps: float) -> int:
        """Return the frame-skip to use for detection.

        Uses the configured value when >= 0; otherwise auto-selects based on clip
        length: short clips are analysed frame-accurately (skip 0), while long
        clips evaluate ~``target_eval_fps`` frames per second for speed.
        """
        if self._frame_skip >= 0:
            return self._frame_skip
        if duration_seconds < self._long_clip_threshold or fps <= 0:
            return 0
        if self._target_eval_fps <= 0:
            return 0
        skip = int(round(fps / self._target_eval_fps)) - 1
        return max(0, skip)

    def _uniform_boundaries(self, clip: ClipSelection) -> list[tuple[float, float]]:
        """Fallback: split the clip into fixed-length windows."""
        duration = clip.duration_seconds
        if duration <= 0.0:
            duration = probe_duration_seconds(Path(clip.source_path))
        if duration <= 0.0:
            return [(0.0, 0.0)]

        window = max(self._min_scene_seconds, 3.0)
        boundaries: list[tuple[float, float]] = []
        cursor = 0.0
        while cursor < duration:
            boundaries.append((cursor, min(duration, cursor + window)))
            cursor += window
        return boundaries

    # ------------------------------------------------------------------ scene build

    def _build_scenes(
        self,
        clip: ClipSelection,
        boundaries: list[tuple[float, float]],
        cache_key: str,
    ) -> list[Scene]:
        """Extract key-frames for each boundary and assemble Scene objects."""
        scenes: list[Scene] = []
        for index, (rel_start, rel_end) in enumerate(boundaries):
            keyframes = self._extract_keyframes(
                clip, index, rel_start, rel_end, cache_key
            )
            scenes.append(
                Scene(
                    index=index,
                    start_seconds=rel_start,
                    end_seconds=rel_end,
                    keyframes=tuple(keyframes),
                )
            )
        return scenes

    def _extract_keyframes(
        self,
        clip: ClipSelection,
        scene_index: int,
        rel_start: float,
        rel_end: float,
        cache_key: str,
    ) -> list[Keyframe]:
        """Sample ``frames_per_scene`` frames evenly within a shot."""
        span = max(0.0, rel_end - rel_start)
        count = self._frames_per_scene
        # Evenly sample within the shot, avoiding the exact cut boundaries.
        offsets = [
            (span * (i + 1) / (count + 1)) if span > 0 else 0.0 for i in range(count)
        ]
        frames: list[Keyframe] = []
        for i, offset in enumerate(offsets):
            clip_seconds = rel_start + offset
            absolute_seconds = clip.source_start_seconds + clip_seconds
            out_path = (
                self._cache_dir
                / cache_key
                / f"scene{scene_index:03d}_kf{i}.jpg"
            )
            if not out_path.exists():
                extract_frame(
                    Path(clip.source_path),
                    absolute_seconds,
                    out_path,
                    width=self._keyframe_width,
                )
            frames.append(Keyframe(image_path=out_path, clip_seconds=clip_seconds))
        return frames

    # ------------------------------------------------------------------ caching

    def _cache_key(self, clip: ClipSelection) -> str:
        """Content-addressed key from file identity, range, and params."""
        source = Path(clip.source_path)
        try:
            stat = source.stat()
            identity = f"{source}:{stat.st_size}:{int(stat.st_mtime)}"
        except OSError:
            identity = str(source)
        params = (
            f"{identity}|{clip.source_start_seconds:.3f}|{clip.source_end_seconds:.3f}"
            f"|{self._detector}|{self._threshold}|{self._downscale}"
            f"|{self._frames_per_scene}|{self._keyframe_width}"
            f"|{self._max_scenes}|{self._frame_skip}|{self._target_eval_fps}"
        )
        return hashlib.sha1(params.encode("utf-8")).hexdigest()[:16]

    def _cache_meta_path(self, cache_key: str) -> Path:
        return self._cache_dir / cache_key / "scenes.json"

    def _load_cache(self, cache_key: str) -> Optional[list[Scene]]:
        meta_path = self._cache_meta_path(cache_key)
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            scenes: list[Scene] = []
            for entry in data:
                keyframes = tuple(
                    Keyframe(Path(kf["image_path"]), float(kf["clip_seconds"]))
                    for kf in entry["keyframes"]
                    if Path(kf["image_path"]).exists()
                )
                if not keyframes:
                    return None  # cache incomplete; rebuild
                scenes.append(
                    Scene(
                        index=int(entry["index"]),
                        start_seconds=float(entry["start_seconds"]),
                        end_seconds=float(entry["end_seconds"]),
                        keyframes=keyframes,
                    )
                )
            return scenes
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def _save_cache(self, cache_key: str, scenes: list[Scene]) -> None:
        meta_path = self._cache_meta_path(cache_key)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        serialisable = [
            {
                "index": scene.index,
                "start_seconds": scene.start_seconds,
                "end_seconds": scene.end_seconds,
                "keyframes": [
                    {"image_path": str(kf.image_path), "clip_seconds": kf.clip_seconds}
                    for kf in scene.keyframes
                ],
            }
            for scene in scenes
        ]
        try:
            with open(meta_path, "w", encoding="utf-8") as handle:
                json.dump(serialisable, handle, indent=2)
        except OSError as exc:
            _log.warning("Could not write scene cache: %s", exc)
