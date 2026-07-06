"""Tests for the environment self-checks."""

from cinesfx.config import AppConfig
from cinesfx.diagnostics import (
    CheckResult,
    check_brain,
    check_resolve,
    check_sound,
    summarize,
)


class _FakeResolve:
    """Minimal stand-in for the Resolve app object."""

    def __init__(self, project=True, timeline=True, clips=2):
        self._project = _FakeProject(timeline, clips) if project else None

    def GetProjectManager(self):
        return _FakeManager(self._project)


class _FakeManager:
    def __init__(self, project):
        self._project = project

    def GetCurrentProject(self):
        return self._project


class _FakeProject:
    def __init__(self, timeline, clips):
        self._timeline = _FakeTimeline(clips) if timeline else None

    def GetName(self):
        return "MyProject"

    def GetCurrentTimeline(self):
        return self._timeline


class _FakeTimeline:
    def __init__(self, clips):
        self._clips = clips

    def GetName(self):
        return "Timeline 1"

    def GetTrackCount(self, track_type):
        return 1 if track_type == "video" else 0

    def GetItemListInTrack(self, track_type, index):
        return ["clip"] * self._clips if track_type == "video" else []


def _config(brain="gemini", sound="freesound"):
    return AppConfig(brain=brain, sound_provider=sound, raw={})


def test_check_resolve_full_chain():
    results = check_resolve(_FakeResolve(clips=3))
    labels = {r.label: r for r in results}
    assert labels["DaVinci Resolve"].ok
    assert labels["Project"].ok and labels["Project"].detail == "MyProject"
    assert labels["Timeline"].ok
    assert labels["Clips on timeline"].ok
    assert "3" in labels["Clips on timeline"].detail


def test_check_resolve_reports_missing_project():
    results = check_resolve(_FakeResolve(project=False))
    labels = {r.label: r for r in results}
    assert labels["DaVinci Resolve"].ok
    assert labels["Project"].ok is False


def test_check_resolve_reports_empty_timeline():
    results = check_resolve(_FakeResolve(clips=0))
    labels = {r.label: r for r in results}
    assert labels["Clips on timeline"].ok is False


def test_check_brain_key_presence(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert check_brain(_config(brain="gemini")).ok is False
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert check_brain(_config(brain="gemini")).ok is True


def test_check_sound_cloud_key(monkeypatch):
    monkeypatch.delenv("FREESOUND_API_KEY", raising=False)
    assert check_sound(_config(sound="freesound")).ok is False
    monkeypatch.setenv("FREESOUND_API_KEY", "x")
    assert check_sound(_config(sound="freesound")).ok is True


def test_check_sound_local_requires_folder(tmp_path):
    config = AppConfig(
        brain="gemini",
        sound_provider="local",
        raw={"sound_providers": {"local": {"library_path": str(tmp_path)}}},
    )
    assert check_sound(config).ok is True

    missing = AppConfig(
        brain="gemini",
        sound_provider="local",
        raw={"sound_providers": {"local": {"library_path": "/no/such/dir/xyz"}}},
    )
    assert check_sound(missing).ok is False


def test_summarize_counts_passes():
    results = [
        CheckResult("A", True, "ok"),
        CheckResult("B", False, "nope"),
    ]
    text = summarize(results)
    assert "1/2 checks passed." in text
    assert "\u2713" in text and "\u2717" in text
