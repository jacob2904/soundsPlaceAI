"""TimelineAgent — the only module that reads from / writes to DaVinci Resolve.

Read side: turns the user's chosen timeline clips into :class:`ClipSelection`
records (source file path + source in/out seconds + timeline position + fps),
*without exporting or uploading any video*.

Write side: imports each downloaded SFX into the Media Pool and appends it to a
dedicated, named SFX audio track at a sample-accurate ``recordFrame`` using
``MediaPool.AppendToTimeline``. Intended gain/pan/fades (which the Resolve
scripting API does not expose for audio clips) are attached as markers + encoded
in the clip name so a Fairlight pass can honour them.

All methods guard Resolve calls with ``getattr``/exceptions so differing API
surfaces across Resolve point releases degrade gracefully instead of crashing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from cinesfx.logging_utils import get_logger
from cinesfx.models import ClipSelection, PlacementPlan, PlannedPlacement
from cinesfx.resolve.connection import ResolveConnectionError, get_resolve

_log = get_logger("resolve.timeline")

# How the user picks which clips to process.
SELECT_CURRENT = "current"   # only the item under the playhead
SELECT_ALL = "all"           # every video item on the timeline (whole video)
SELECT_COLOR = "color"       # only items tagged with a given clip color


class TimelineAgent:
    """Read selections from, and write SFX into, the current Resolve timeline."""

    def __init__(
        self, sfx_track_name: str = "CineSFX", resolve_obj: Optional[Any] = None
    ) -> None:
        self._sfx_track_name = sfx_track_name
        self._resolve = get_resolve(resolve_obj)
        self._project = self._current_project()
        self._timeline = self._current_timeline()

    # ------------------------------------------------------------------ read side

    def timeline_fps(self) -> float:
        """Return the timeline frame rate as a float (defaults to 24.0)."""
        try:
            value = self._project.GetSetting("timelineFrameRate")
            return float(value) if value else 24.0
        except (ValueError, TypeError, AttributeError):
            return 24.0

    def read_selection(
        self, mode: str = SELECT_CURRENT, color: Optional[str] = None
    ) -> list[ClipSelection]:
        """Return the clips the user asked to sound-design.

        Args:
            mode: One of ``current`` / ``all`` / ``color``.
            color: Required when ``mode == 'color'`` (e.g. "Orange"); only clips
                with that clip color are returned.

        Returns:
            A list of :class:`ClipSelection` (empty if nothing matched).
        """
        fps = self.timeline_fps()
        items = self._collect_video_items(mode, color)
        selections: list[ClipSelection] = []
        for item in items:
            selection = self._to_selection(item, fps)
            if selection is not None:
                selections.append(selection)
        _log.info("Read %d clip(s) from timeline (mode=%s)", len(selections), mode)
        return selections

    def _collect_video_items(self, mode: str, color: Optional[str]) -> list[Any]:
        """Gather the raw Resolve TimelineItem objects for the given mode."""
        if mode == SELECT_CURRENT:
            current = _safe_call(self._timeline, "GetCurrentVideoItem")
            return [current] if current else []

        track_count = int(_safe_call(self._timeline, "GetTrackCount", "video") or 0)
        items: list[Any] = []
        for index in range(1, track_count + 1):
            track_items = _safe_call(
                self._timeline, "GetItemListInTrack", "video", index
            )
            if track_items:
                items.extend(track_items)

        if mode == SELECT_COLOR:
            if not color:
                raise ValueError("mode 'color' requires a 'color' argument.")
            items = [
                item
                for item in items
                if str(_safe_call(item, "GetClipColor") or "").lower() == color.lower()
            ]
        return items

    def _to_selection(self, item: Any, fps: float) -> Optional[ClipSelection]:
        """Convert a Resolve TimelineItem into a :class:`ClipSelection`."""
        try:
            media_item = _safe_call(item, "GetMediaPoolItem")
            if media_item is None:
                return None
            source_path = _safe_call(media_item, "GetClipProperty", "File Path")
            if not source_path:
                return None

            start_seconds, end_seconds = self._source_seconds(item, media_item, fps)
            return ClipSelection(
                item_id=str(_safe_call(item, "GetUniqueId") or id(item)),
                name=str(_safe_call(item, "GetName") or "clip"),
                source_path=str(source_path),
                timeline_start_frame=int(_safe_call(item, "GetStart") or 0),
                timeline_end_frame=int(_safe_call(item, "GetEnd") or 0),
                source_start_seconds=start_seconds,
                source_end_seconds=end_seconds,
                fps=fps,
            )
        except Exception as exc:  # noqa: BLE001 - skip a bad item, keep the rest
            _log.warning("Could not read a timeline item: %s", exc)
            return None

    def _source_seconds(
        self, item: Any, media_item: Any, fps: float
    ) -> tuple[float, float]:
        """Return the clip's source in/out points in seconds.

        Prefers the direct ``GetSourceStartTime``/``GetSourceEndTime`` API and
        falls back to frame-based math using the source clip's own frame rate.
        """
        start_time = _safe_call(item, "GetSourceStartTime")
        end_time = _safe_call(item, "GetSourceEndTime")
        if isinstance(start_time, (int, float)) and isinstance(end_time, (int, float)):
            return float(start_time), float(end_time)

        source_fps = _clip_fps(media_item, fps)
        start_frame = float(_safe_call(item, "GetSourceStartFrame") or 0)
        end_frame = float(_safe_call(item, "GetSourceEndFrame") or 0)
        if source_fps <= 0:
            source_fps = fps or 24.0
        return start_frame / source_fps, end_frame / source_fps

    # ------------------------------------------------------------------ write side

    def apply_plan(self, plan: PlacementPlan) -> int:
        """Insert every placement in ``plan`` onto the SFX tracks.

        Args:
            plan: The plan produced by the PlacementAgent.

        Returns:
            The number of placements successfully inserted.
        """
        if plan.count == 0:
            _log.info("Nothing to insert (empty plan).")
            return 0

        media_pool = _safe_call(self._project, "GetMediaPool")
        if media_pool is None:
            raise ResolveConnectionError("Could not access the project Media Pool.")

        max_lane = max(placement.track_lane for placement in plan.placements)
        base_track_index = self._ensure_sfx_tracks(max_lane + 1)

        inserted = 0
        for placement in plan.placements:
            if self._insert_one(media_pool, placement, base_track_index):
                inserted += 1
        _log.info("Inserted %d/%d placement(s).", inserted, plan.count)
        return inserted

    def _insert_one(
        self, media_pool: Any, placement: PlannedPlacement, base_track_index: int
    ) -> bool:
        """Import + append a single SFX and annotate it. Returns success."""
        try:
            imported = _safe_call(media_pool, "ImportMedia", [str(placement.audio_file)])
            if not imported:
                _log.warning("Import failed for %s", placement.audio_file)
                return False
            media_item = imported[0]

            track_index = base_track_index + placement.track_lane
            end_frame = self._audio_end_frame(media_item, placement)
            clip_info = {
                "mediaPoolItem": media_item,
                "startFrame": 0,
                "endFrame": end_frame,
                "mediaType": 2,  # audio only
                "trackIndex": track_index,
                "recordFrame": placement.record_frame,
            }
            appended = _safe_call(media_pool, "AppendToTimeline", [clip_info])
            if not appended:
                _log.warning("Append failed for %s", placement.cue.description)
                return False

            self._annotate(appended[0], placement)
            return True
        except Exception as exc:  # noqa: BLE001 - one failure must not abort the batch
            _log.warning("Placement failed for '%s': %s", placement.cue.description, exc)
            return False

    def _annotate(self, audio_item: Any, placement: PlannedPlacement) -> None:
        """Record intended gain/pan/fades on the inserted audio clip.

        The Resolve API does not expose audio clip gain/pan, so the intent is
        stored as a marker with JSON customData and encoded in the clip name for a
        follow-up Fairlight pass (or a companion DaVinci macro).
        """
        cue = placement.cue
        label = (
            f"{cue.description} | {placement.gain_db:+.1f}dB "
            f"pan {placement.pan:+.2f}"
        )
        _safe_call(audio_item, "SetName", label)
        custom = json.dumps(
            {
                "gain_db": placement.gain_db,
                "pan": placement.pan,
                "fade_in": placement.fade_in_frames,
                "fade_out": placement.fade_out_frames,
                "kind": cue.kind.value,
                "query": cue.query,
                "provider": placement.asset.provider,
                "asset_id": placement.asset.asset_id,
            }
        )
        _safe_call(
            audio_item,
            "AddMarker",
            0,
            "Cyan",
            "CineSFX",
            cue.description,
            1,
            custom,
        )

    def _ensure_sfx_tracks(self, lanes_needed: int) -> int:
        """Ensure ``lanes_needed`` named SFX audio tracks exist.

        Returns the 1-based track index of the first SFX lane.
        """
        existing = int(_safe_call(self._timeline, "GetTrackCount", "audio") or 0)
        first_new_index = existing + 1
        for lane in range(lanes_needed):
            _safe_call(self._timeline, "AddTrack", "audio")
            index = first_new_index + lane
            name = self._sfx_track_name if lane == 0 else f"{self._sfx_track_name} {lane + 1}"
            _safe_call(self._timeline, "SetTrackName", "audio", index, name)
        return first_new_index

    @staticmethod
    def _audio_end_frame(media_item: Any, placement: PlannedPlacement) -> int:
        """Compute the endFrame (source out) for the appended audio."""
        frames = _safe_call(media_item, "GetClipProperty", "Frames")
        try:
            total = int(frames) if frames else 0
        except (TypeError, ValueError):
            total = 0
        # Prefer the planned duration (fade window) but never exceed the asset.
        fps = placement.clip.fps or 24.0
        planned = 0
        if placement.cue.duration_seconds > 0:
            planned = int(round(placement.cue.duration_seconds * fps))
        candidates = [value for value in (total, planned) if value > 0]
        if not candidates:
            return 0
        return max(0, min(candidates) - 1)

    # ------------------------------------------------------------------ internals

    def _current_project(self) -> Any:
        manager = _safe_call(self._resolve, "GetProjectManager")
        project = _safe_call(manager, "GetCurrentProject") if manager else None
        if project is None:
            raise ResolveConnectionError("No project is currently open in Resolve.")
        return project

    def _current_timeline(self) -> Any:
        timeline = _safe_call(self._project, "GetCurrentTimeline")
        if timeline is None:
            raise ResolveConnectionError("No timeline is currently open in Resolve.")
        return timeline


def _safe_call(obj: Any, method: str, *args: Any) -> Any:
    """Call ``obj.method(*args)`` if it exists, returning ``None`` on failure."""
    if obj is None:
        return None
    func = getattr(obj, method, None)
    if func is None:
        return None
    try:
        return func(*args)
    except Exception as exc:  # noqa: BLE001 - normalise Resolve bridge errors
        _log.debug("Resolve call %s failed: %s", method, exc)
        return None


def _clip_fps(media_item: Any, default_fps: float) -> float:
    """Return the source clip's frame rate, or ``default_fps`` if unknown."""
    value = _safe_call(media_item, "GetClipProperty", "FPS")
    try:
        return float(value) if value else default_fps
    except (TypeError, ValueError):
        return default_fps
