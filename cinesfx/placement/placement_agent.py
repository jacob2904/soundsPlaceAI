"""PlacementAgent — turns cues + downloaded audio into a concrete timeline plan.

This agent is deliberately split from the Resolve I/O layer: it computes *what*
should happen (record frames, lanes, gain, pan, fades) as pure data, which makes
it fully unit-testable. The TimelineAgent then executes the plan against Resolve.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cinesfx.logging_utils import get_logger
from cinesfx.models import (
    ClipSelection,
    PlacementPlan,
    PlannedPlacement,
    Scene,
    SfxCue,
    SfxKind,
    SoundAsset,
)
from cinesfx.placement.spatial import (
    SpatialSettings,
    compute_spatial,
    seconds_to_frames,
)

_log = get_logger("placement")


class PlacementAgent:
    """Compute concrete, non-overlapping SFX placements for a plan."""

    def __init__(self, placement_cfg: dict[str, Any], spatial_cfg: dict[str, Any]) -> None:
        self._max_lanes = max(1, int(placement_cfg.get("max_lanes", 3)))
        self._default_fade_ms = float(placement_cfg.get("default_fade_ms", 40))
        self._headroom_db = float(placement_cfg.get("headroom_db", -3.0))
        self._ambience_gain_db = float(placement_cfg.get("ambience_gain_db", -18.0))
        self._spatial = SpatialSettings(
            enabled=bool(spatial_cfg.get("enabled", True)),
            max_distance_attenuation_db=float(
                spatial_cfg.get("max_distance_attenuation_db", -12.0)
            ),
            max_pan=float(spatial_cfg.get("max_pan", 0.8)),
        )

    def plan_for_clip(
        self,
        clip: ClipSelection,
        scenes: list[Scene],
        resolved: list[tuple[SfxCue, SoundAsset, Path]],
    ) -> PlacementPlan:
        """Build a :class:`PlacementPlan` for one clip.

        Args:
            clip: The clip being sound-designed.
            scenes: The clip's scenes (used to clamp cue onsets into windows).
            resolved: Tuples of (cue, chosen asset, downloaded audio path).

        Returns:
            A plan with one :class:`PlannedPlacement` per resolvable cue.
        """
        plan = PlacementPlan()
        scene_by_index = {scene.index: scene for scene in scenes}
        # Track the last occupied frame per lane to avoid overlaps.
        lane_free_at: list[int] = [clip.timeline_start_frame] * self._max_lanes
        fade_frames = seconds_to_frames(self._default_fade_ms / 1000.0, clip.fps)

        for cue, asset, audio_file in self._ordered(resolved):
            onset = self._clamp_onset(cue, scene_by_index)
            record_frame = clip.timeline_start_frame + seconds_to_frames(onset, clip.fps)
            duration_frames = self._cue_duration_frames(cue, asset, clip, scene_by_index)
            lane = self._assign_lane(lane_free_at, record_frame, duration_frames)
            if lane is None:
                plan.warnings.append(
                    f"No free SFX lane for '{cue.description}' at {onset:.2f}s; skipped."
                )
                continue

            gain_db = self._final_gain(cue)
            spatial = compute_spatial(cue.distance, cue.pan, self._spatial)

            plan.add(
                PlannedPlacement(
                    clip=clip,
                    cue=cue,
                    asset=asset,
                    audio_file=audio_file,
                    record_frame=record_frame,
                    track_lane=lane,
                    gain_db=round(gain_db + spatial.gain_offset_db, 2),
                    pan=spatial.pan,
                    fade_in_frames=fade_frames,
                    fade_out_frames=fade_frames,
                    duration_frames=duration_frames,
                )
            )
            lane_free_at[lane] = record_frame + max(1, duration_frames)

        _log.info(
            "Planned %d placement(s) for %s (%d warning(s))",
            plan.count,
            clip.name,
            len(plan.warnings),
        )
        return plan

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _ordered(
        resolved: list[tuple[SfxCue, SoundAsset, Path]]
    ) -> list[tuple[SfxCue, SoundAsset, Path]]:
        """Order cues by onset so lane packing is deterministic."""
        return sorted(resolved, key=lambda triple: triple[0].onset_seconds)

    @staticmethod
    def _clamp_onset(cue: SfxCue, scene_by_index: dict[int, Scene]) -> float:
        """Clamp a cue's onset into its scene window when known."""
        scene = scene_by_index.get(cue.scene_index)
        if scene is None:
            return max(0.0, cue.onset_seconds)
        return min(max(cue.onset_seconds, scene.start_seconds), scene.end_seconds)

    def _cue_duration_frames(
        self,
        cue: SfxCue,
        asset: SoundAsset,
        clip: ClipSelection,
        scene_by_index: dict[int, Scene],
    ) -> int:
        """Decide how many frames a cue should occupy."""
        if cue.duration_seconds > 0:
            seconds = cue.duration_seconds
        elif asset.duration_seconds > 0:
            seconds = asset.duration_seconds
        elif cue.kind is SfxKind.AMBIENCE:
            scene = scene_by_index.get(cue.scene_index)
            seconds = scene.duration_seconds if scene else clip.duration_seconds
        else:
            seconds = 1.0  # sensible default for a spot effect of unknown length
        return max(1, seconds_to_frames(seconds, clip.fps))

    def _assign_lane(
        self, lane_free_at: list[int], record_frame: int, duration_frames: int
    ) -> int | None:
        """Return the first lane free at ``record_frame``, or ``None``."""
        for lane, free_at in enumerate(lane_free_at):
            if record_frame >= free_at:
                return lane
        return None

    def _final_gain(self, cue: SfxCue) -> float:
        """Combine the cue's gain with kind defaults and the headroom ceiling."""
        base = cue.gain_db
        if cue.kind is SfxKind.AMBIENCE:
            base = min(base, self._ambience_gain_db)
        return min(base, self._headroom_db) if base > self._headroom_db else base
