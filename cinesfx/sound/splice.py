"""Splice provider — indexes the local Splice samples folder.

Splice does **not** publish an official developer API for searching/downloading
samples (the only programmatic access is unofficial, reverse-engineered gRPC that
violates their terms and breaks often). The reliable, ToS-friendly, and *seamless*
integration is therefore to read the samples the user has already synced with the
Splice desktop app from their **local Splice folder** — exactly how DAWs like
Ableton integrate Splice.

By default Splice stores samples in ``~/Splice`` (or ``~/Documents/Splice``); the
folder is user-configurable in the Splice app, so ``library_path`` can override it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError
from cinesfx.sound.local import LocalLibraryIndex

_log = get_logger("sound.splice")


def default_splice_paths() -> list[Path]:
    """Return the conventional default Splice sample locations for this user."""
    home = Path.home()
    return [
        home / "Splice" / "sounds",
        home / "Splice",
        home / "Documents" / "Splice" / "sounds",
        home / "Documents" / "Splice",
    ]


def resolve_splice_library(configured: Optional[str]) -> Path:
    """Resolve the Splice library folder from config or OS defaults.

    Args:
        configured: The ``library_path`` from config (may be None/empty).

    Returns:
        The first existing candidate directory.

    Raises:
        SoundProviderError: If no Splice folder can be found.
    """
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir():
            return path
        raise SoundProviderError(
            f"Configured Splice library_path does not exist: {path}"
        )

    for candidate in default_splice_paths():
        if candidate.is_dir():
            _log.info("Using detected Splice folder: %s", candidate)
            return candidate

    raise SoundProviderError(
        "Could not find a Splice folder. Set sound_providers.splice.library_path "
        "in config.yaml to your Splice samples folder (default is ~/Splice)."
    )


class SpliceProvider(SoundProvider):
    """Serve sounds from the user's local Splice samples folder."""

    name = "splice"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        library = resolve_splice_library(settings.get("library_path"))
        self._index = LocalLibraryIndex(library)

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
                    license_name="Splice (local library)",
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        if asset.local_path and asset.local_path.exists():
            return asset.local_path
        path = Path(asset.asset_id)
        if path.exists():
            return path
        raise SoundProviderError(f"Splice sample not found: {asset.asset_id}")
