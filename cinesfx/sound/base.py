"""Abstract base class + shared filters for sound-effect providers."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from cinesfx.models import SoundAsset


class SoundProviderError(RuntimeError):
    """Raised when a sound provider cannot be used or a request fails."""


@dataclass(frozen=True)
class SearchFilters:
    """Optional constraints applied to a catalogue search.

    Attributes:
        max_results: Upper bound on returned assets.
        max_duration_seconds: Prefer assets no longer than this (0 = ignore).
        sort: Provider-specific sort hint ("best-match", "popular", ...).
    """

    max_results: int = 10
    max_duration_seconds: float = 0.0
    sort: str = "best-match"


class SoundProvider(abc.ABC):
    """A pluggable sound-effects catalogue (cloud API or local folder)."""

    name: str = "base"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        self._settings = dict(settings)
        self._cache_dir = cache_dir

    @abc.abstractmethod
    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        """Return candidate assets matching ``query`` (best first)."""

    @abc.abstractmethod
    def download(self, asset: SoundAsset) -> Path:
        """Download (or resolve) the asset's audio and return a local path."""

    def best_match(
        self, query: str, filters: Optional[SearchFilters] = None
    ) -> Optional[SoundAsset]:
        """Search and return the single best asset, or ``None`` if none found."""
        results = self.search(query, filters or SearchFilters())
        return results[0] if results else None
