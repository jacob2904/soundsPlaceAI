"""Abstract base class for brain (LLM) providers."""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any

from cinesfx.models import Scene, SfxCue


class BrainError(RuntimeError):
    """Raised when a brain provider cannot be used or a request fails."""


class BrainProvider(abc.ABC):
    """A pluggable scene-understanding + SFX-planning engine.

    Concrete providers wrap a vision-capable LLM. They receive the small
    key-frames produced by :class:`~cinesfx.analysis.SceneAgent` and return a list
    of :class:`~cinesfx.models.SfxCue` describing what to place and when.
    """

    name: str = "base"

    def __init__(self, settings: dict[str, Any]) -> None:
        self._settings = dict(settings)

    @abc.abstractmethod
    def describe_and_plan(
        self, scenes: list[Scene], context: dict[str, Any]
    ) -> list[SfxCue]:
        """Analyse scenes and return sound-effect cues.

        Args:
            scenes: Ordered scenes for a single clip (clip-relative timings).
            context: Extra hints (clip name, duration, max cues per scene, style).

        Returns:
            A list of cues. Implementations must clamp cue onsets into their
            scene windows and skip malformed model output rather than raise.
        """

    @staticmethod
    def _collect_images(scenes: list[Scene]) -> list[Path]:
        """Return all key-frame image paths across ``scenes`` in order."""
        images: list[Path] = []
        for scene in scenes:
            for keyframe in scene.keyframes:
                if keyframe.image_path.exists():
                    images.append(keyframe.image_path)
        return images
