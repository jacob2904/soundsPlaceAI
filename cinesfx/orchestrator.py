"""Orchestrator — wires the agents into one efficient pipeline.

Per-clip work (scene detection → brain planning → sound search/download →
placement planning) is CPU/network-bound and runs concurrently across clips in a
thread pool. All Resolve *writes* are performed afterwards on the calling thread,
because the Resolve scripting bridge is not safe for concurrent writes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from cinesfx.analysis import SceneAgent
from cinesfx.brain import BrainProvider, create_brain
from cinesfx.config import AppConfig, load_config
from cinesfx.logging_utils import configure_logging, get_logger
from cinesfx.models import (
    ClipSelection,
    PlacementPlan,
    Scene,
    SfxCue,
    SoundAsset,
)
from cinesfx.placement import PlacementAgent
from cinesfx.resolve import TimelineAgent
from cinesfx.sound import SoundProvider, create_sound_provider
from cinesfx.sound.base import SearchFilters

_log = get_logger("orchestrator")


@dataclass
class ClipResult:
    """The per-clip outcome carried through the pipeline."""

    clip: ClipSelection
    scenes: list[Scene] = field(default_factory=list)
    plan: PlacementPlan = field(default_factory=PlacementPlan)
    error: Optional[str] = None


class Orchestrator:
    """Coordinates the full analyse → plan → place pipeline."""

    def __init__(
        self,
        config: AppConfig,
        timeline_agent: Optional[TimelineAgent] = None,
        brain: Optional[BrainProvider] = None,
        sound_provider: Optional[SoundProvider] = None,
    ) -> None:
        """Create the orchestrator.

        Args:
            config: Loaded application configuration.
            timeline_agent: Optional pre-built TimelineAgent (injected for tests).
            brain: Optional pre-built brain (injected for tests).
            sound_provider: Optional pre-built sound provider (injected for tests).
        """
        self._config = config
        runtime = config.runtime()
        configure_logging(str(runtime.get("log_level", "INFO")))

        self._cache_dir: Path = config.cache_dir()
        self._max_workers = max(1, int(runtime.get("max_workers", 4)))
        # How many scenes are described per brain call. Keeping this bounded is
        # what makes long clips (hundreds of shots) practical and affordable.
        self._scenes_per_batch = max(1, int(runtime.get("scenes_per_brain_batch", 12)))

        self._timeline = timeline_agent
        self._brain = brain
        self._sound = sound_provider
        self._scene_agent = SceneAgent(config.analysis(), self._cache_dir)
        self._placement_agent = PlacementAgent(config.placement(), config.spatial())

    # ------------------------------------------------------------------ public API

    def run(
        self,
        mode: str = "current",
        color: Optional[str] = None,
        dry_run: bool = False,
        progress: Optional[Callable[[str], None]] = None,
    ) -> list[ClipResult]:
        """Analyse the selection and (unless ``dry_run``) place the SFX.

        Args:
            mode: Selection mode passed to the TimelineAgent.
            color: Clip color for ``mode == 'color'``.
            dry_run: If True, build and report the plan but do not edit Resolve.
            progress: Optional callback invoked with human-readable status
                strings (used by the UI to show live progress).

        Returns:
            A list of :class:`ClipResult`, one per selected clip.

        Raises:
            LicenseError: If a non-dry-run is attempted without a valid license.
        """
        report = progress or (lambda _message: None)

        # Preview (dry-run) is always free; placing SFX requires activation.
        if not dry_run:
            self._require_license()

        timeline = self._require_timeline()
        report("Reading timeline selection…")
        clips = timeline.read_selection(mode=mode, color=color)
        if not clips:
            _log.warning("No clips matched the selection (mode=%s).", mode)
            report("No matching clips found.")
            return []

        report(f"Analysing {len(clips)} clip(s)…")
        results = self._process_clips_concurrently(clips, report)

        if dry_run:
            _log.info("Dry-run: %d clip(s) planned; no timeline changes made.",
                      len(results))
            report("Preview ready (no changes made).")
            return results

        report("Placing sound effects on the timeline…")
        self._apply(timeline, results)
        report("Done.")
        return results

    def report(self, results: list[ClipResult]) -> str:
        """Return a human-readable summary of a run's plans."""
        lines: list[str] = []
        total = 0
        for result in results:
            if result.error:
                lines.append(f"✗ {result.clip.name}: ERROR — {result.error}")
                continue
            lines.append(
                f"● {result.clip.name}: {len(result.scenes)} scene(s), "
                f"{result.plan.count} SFX"
            )
            for placement in result.plan.placements:
                seconds = (
                    (placement.record_frame - result.clip.timeline_start_frame)
                    / (result.clip.fps or 24.0)
                )
                lines.append(
                    f"    +{seconds:6.2f}s  lane{placement.track_lane}  "
                    f"{placement.gain_db:+5.1f}dB pan{placement.pan:+.2f}  "
                    f"[{placement.asset.provider}] {placement.cue.description}"
                )
            for warning in result.plan.warnings:
                lines.append(f"    ! {warning}")
            total += result.plan.count
        lines.append(f"\nTotal planned SFX: {total}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ pipeline

    def _process_clips_concurrently(
        self, clips: list[ClipSelection], report: Callable[[str], None]
    ) -> list[ClipResult]:
        """Run the analyse+plan stage for every clip across a thread pool."""
        results: list[ClipResult] = []
        done = 0
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {
                pool.submit(self._process_single_clip, clip): clip for clip in clips
            }
            for future in as_completed(futures):
                clip = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # noqa: BLE001 - capture per-clip failure
                    _log.warning("Clip '%s' failed: %s", clip.name, exc)
                    results.append(ClipResult(clip=clip, error=str(exc)))
                done += 1
                report(f"Analysed {done}/{len(clips)} clip(s)…")
        # Preserve timeline order for a readable report.
        results.sort(key=lambda item: item.clip.timeline_start_frame)
        return results

    def _process_single_clip(self, clip: ClipSelection) -> ClipResult:
        """Full analyse+plan for one clip (safe to run in a worker thread)."""
        scenes = self._scene_agent.analyze(clip)
        cues = self._plan_cues_batched(clip, scenes)
        resolved = self._resolve_cues(clip, cues)
        plan = self._placement_agent.plan_for_clip(clip, scenes, resolved)
        return ClipResult(clip=clip, scenes=scenes, plan=plan)

    def _plan_cues_batched(
        self, clip: ClipSelection, scenes: list[Scene]
    ) -> list[SfxCue]:
        """Ask the brain to plan cues, batching scenes for long clips.

        Splitting a long clip's scenes into small batches keeps each LLM request
        cheap and within context limits, while still covering the whole video.
        Cues keep their real ``scene_index`` so placement maps them correctly.
        """
        brain = self._require_brain()
        context = self._brain_context(clip)
        cues: list[SfxCue] = []
        for start in range(0, len(scenes), self._scenes_per_batch):
            batch = scenes[start : start + self._scenes_per_batch]
            try:
                cues.extend(brain.describe_and_plan(batch, context))
            except Exception as exc:  # noqa: BLE001 - one batch must not kill the clip
                _log.warning(
                    "Brain batch %d for '%s' failed: %s",
                    start // self._scenes_per_batch,
                    clip.name,
                    exc,
                )
        return cues

    def _resolve_cues(
        self, clip: ClipSelection, cues: list[SfxCue]
    ) -> list[tuple[SfxCue, SoundAsset, Path]]:
        """Search + download the best asset for each cue; skip on failure."""
        provider = self._require_sound()
        resolved: list[tuple[SfxCue, SoundAsset, Path]] = []
        for cue in cues:
            filters = SearchFilters(
                max_results=8,
                max_duration_seconds=self._max_asset_seconds(cue, clip),
            )
            try:
                asset = provider.best_match(cue.query, filters)
                if asset is None:
                    _log.info("No asset found for '%s'", cue.query)
                    continue
                audio_path = provider.download(asset)
                resolved.append((cue, asset, audio_path))
            except Exception as exc:  # noqa: BLE001 - one bad cue must not abort
                _log.warning("Could not resolve cue '%s': %s", cue.query, exc)
        return resolved

    def _apply(self, timeline: TimelineAgent, results: list[ClipResult]) -> None:
        """Write every clip's plan to the timeline (single-threaded)."""
        for result in results:
            if result.error or result.plan.count == 0:
                continue
            try:
                timeline.apply_plan(result.plan)
            except Exception as exc:  # noqa: BLE001 - continue with other clips
                result.error = f"insertion failed: {exc}"
                _log.warning("Insertion failed for '%s': %s", result.clip.name, exc)

    # ------------------------------------------------------------------ helpers

    def _brain_context(self, clip: ClipSelection) -> dict[str, Any]:
        placement = self._config.placement()
        analysis = self._config.analysis()
        brain_frames = analysis.get("brain_frames_per_scene")
        return {
            "clip_name": clip.name,
            "duration_seconds": clip.duration_seconds,
            "max_cues_per_scene": int(placement.get("max_cues_per_scene", 4)),
            "style": placement.get("style", "natural, filmic"),
            # Token-efficiency knobs consumed by the brain providers.
            "brain_frames_per_scene": (
                int(brain_frames) if brain_frames is not None else 1
            ),
            "max_images_per_request": int(analysis.get("max_images_per_request", 12)),
            "image_detail": str(analysis.get("image_detail", "low")),
        }

    @staticmethod
    def _max_asset_seconds(cue: SfxCue, clip: ClipSelection) -> float:
        """Cap asset length: spot effects short, ambiences up to clip length."""
        if cue.kind.value == "ambience":
            return max(0.0, clip.duration_seconds)
        if cue.duration_seconds > 0:
            return cue.duration_seconds * 2.0
        return 12.0

    @staticmethod
    def _require_license() -> None:
        """Ensure a valid license is active before writing to the timeline.

        Previewing (dry-run) is always free; placing SFX is the paid action.

        Raises:
            LicenseError: If no valid license is activated.
        """
        from cinesfx.licensing import LicenseError
        from cinesfx.settings import get_license_status

        status = get_license_status()
        if not status.activated:
            raise LicenseError(
                "Placing sound effects requires an activated CineSFX license "
                "(one-time purchase, lifetime). " + status.message + " You can "
                "still use Preview (dry-run) for free. Activate your key in the "
                "panel or with: python -m scripts.run_cli --activate <KEY>"
            )

    def _require_timeline(self) -> TimelineAgent:
        if self._timeline is None:
            self._timeline = TimelineAgent(
                sfx_track_name=str(
                    self._config.placement().get("sfx_track_name", "CineSFX")
                )
            )
        return self._timeline

    def _require_brain(self) -> BrainProvider:
        if self._brain is None:
            self._brain = create_brain(self._config)
        return self._brain

    def _require_sound(self) -> SoundProvider:
        if self._sound is None:
            self._sound = create_sound_provider(self._config)
        return self._sound


def build_orchestrator(
    config_path: Optional[str] = None, env_path: Optional[str] = None
) -> Orchestrator:
    """Convenience builder that loads config and returns an Orchestrator."""
    config = load_config(config_path=config_path, env_path=env_path)
    return Orchestrator(config)
