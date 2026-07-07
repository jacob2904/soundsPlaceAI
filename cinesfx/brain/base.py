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
    def _collect_images(
        scenes: list[Scene],
        per_scene_limit: int | None = None,
        max_total: int | None = None,
    ) -> list[Path]:
        """Return key-frame image paths across ``scenes``, in order.

        Fewer images means fewer (expensive) vision tokens, so this can trim the
        set two ways while keeping representative coverage:

        Args:
            per_scene_limit: Max images to send per scene (evenly sampled, so a
                limit of 1 keeps the middle/most representative frame). ``None``
                keeps every extracted frame.
            max_total: Hard cap on the images for the whole request (evenly
                sampled across all scenes). ``None`` means no cap.
        """
        images: list[Path] = []
        for scene in scenes:
            frames = [
                keyframe.image_path
                for keyframe in scene.keyframes
                if keyframe.image_path.exists()
            ]
            images.extend(_sample_evenly(frames, per_scene_limit))
        return _sample_evenly(images, max_total)


def _sample_evenly(items: list[Path], limit: int | None) -> list[Path]:
    """Return at most ``limit`` items, evenly spaced (middle-of-bucket biased)."""
    count = len(items)
    if not limit or limit <= 0 or count <= limit:
        return list(items)
    step = count / limit
    return [items[min(count - 1, int(index * step + step / 2))] for index in range(limit)]
