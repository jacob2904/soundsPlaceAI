"""Soundly provider — indexes a local Soundly library folder.

Soundly does not publish a public cloud API, so the fastest and most reliable
integration is to read its **local library folder** (where Soundly stores the
sound effects the user has downloaded / added). This also lets us leverage the
same effects the user already relies on inside Soundly, while our PlacementAgent
handles the "realistic placement in the scene" (pan/distance) part.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError
from cinesfx.sound.local import LocalLibraryIndex

_log = get_logger("sound.soundly")


class SoundlyProvider(SoundProvider):
    """Serve sound effects from the user's local Soundly library folder."""

    name = "soundly"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        library_path = _require_soundly_path(settings)
        self._index = LocalLibraryIndex(library_path)

    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        assets: list[SoundAsset] = []
        for path, _score in self._index.rank(query, max(1, filters.max_results)):
            assets.append(
                SoundAsset(
                    provider=self.name,
                    asset_id=str(path),
                    title=path.stem,
                    duration_seconds=0.0,
                    local_path=path,
                    license_name="Soundly (local library)",
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        if asset.local_path and asset.local_path.exists():
            return asset.local_path
        path = Path(asset.asset_id)
        if path.exists():
            return path
        raise SoundProviderError(f"Soundly library file not found: {asset.asset_id}")


def _require_soundly_path(settings: dict[str, Any]) -> Path:
    """Extract and validate the Soundly ``library_path`` from settings."""
    raw: Optional[str] = settings.get("library_path")
    if not raw:
        raise SoundProviderError(
            "No 'library_path' configured for the Soundly provider. Point it at your "
            "local Soundly library folder in config.yaml "
            "(sound_providers.soundly.library_path)."
        )
    return Path(raw).expanduser()
