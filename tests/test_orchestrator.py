"""End-to-end pipeline test with fake agents (no Resolve, no network, no ffmpeg)."""

from pathlib import Path

from cinesfx.config import AppConfig
from cinesfx.models import (
    ClipSelection,
    Keyframe,
    PlacementPlan,
    Scene,
    SfxCue,
    SoundAsset,
)
from cinesfx.orchestrator import Orchestrator
from cinesfx.sound.base import SearchFilters, SoundProvider


class _FakeTimeline:
    def __init__(self, clips):
        self._clips = clips
        self.applied = []

    def read_selection(self, mode="current", color=None):
        return self._clips

    def apply_plan(self, plan: PlacementPlan) -> int:
        self.applied.append(plan)
        return plan.count


class _FakeBrain:
    def describe_and_plan(self, scenes, context):
        return [
            SfxCue(description="door", query="door creak", onset_seconds=1.0, scene_index=0),
            SfxCue(description="wind", query="wind ambience", onset_seconds=0.0, scene_index=0),
        ]


class _FakeSound(SoundProvider):
    name = "fake"

    def __init__(self):
        super().__init__({}, Path("/tmp"))

    def search(self, query, filters: SearchFilters):
        return [SoundAsset(provider="fake", asset_id=query, title=query, duration_seconds=1.0)]

    def download(self, asset: SoundAsset) -> Path:
        return Path(f"/tmp/{asset.asset_id}.mp3")


class _FakeSceneAgent:
    def analyze(self, clip):
        return [Scene(0, 0.0, 5.0, (Keyframe(Path("/tmp/x.jpg"), 2.5),))]


def _config() -> AppConfig:
    return AppConfig(
        brain="gemini",
        sound_provider="freesound",
        raw={
            "placement": {"max_lanes": 3, "sfx_track_name": "CineSFX"},
            "spatial": {"enabled": True},
            "runtime": {"max_workers": 2, "log_level": "WARNING"},
        },
    )


def _clip() -> ClipSelection:
    return ClipSelection(
        item_id="c1",
        name="shot1",
        source_path="/tmp/a.mov",
        timeline_start_frame=0,
        timeline_end_frame=120,
        source_start_seconds=0.0,
        source_end_seconds=5.0,
        fps=24.0,
    )


def _build_orchestrator(timeline):
    orch = Orchestrator(
        _config(),
        timeline_agent=timeline,
        brain=_FakeBrain(),
        sound_provider=_FakeSound(),
    )
    orch._scene_agent = _FakeSceneAgent()  # avoid ffmpeg in tests
    return orch


def test_dry_run_plans_but_does_not_apply():
    timeline = _FakeTimeline([_clip()])
    orch = _build_orchestrator(timeline)
    results = orch.run(mode="current", dry_run=True)
    assert len(results) == 1
    assert results[0].plan.count == 2
    assert timeline.applied == []  # nothing written


def test_full_run_applies_plan():
    timeline = _FakeTimeline([_clip()])
    orch = _build_orchestrator(timeline)
    results = orch.run(mode="current", dry_run=False)
    assert len(timeline.applied) == 1
    assert timeline.applied[0].count == 2


def test_report_is_human_readable():
    timeline = _FakeTimeline([_clip()])
    orch = _build_orchestrator(timeline)
    results = orch.run(mode="current", dry_run=True)
    report = orch.report(results)
    assert "shot1" in report
    assert "Total planned SFX: 2" in report


def test_empty_selection_returns_no_results():
    timeline = _FakeTimeline([])
    orch = _build_orchestrator(timeline)
    assert orch.run(mode="current", dry_run=True) == []
