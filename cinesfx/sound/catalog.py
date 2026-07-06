"""Catalog provider — place sounds from the user's own indexed sound library.

Unlike the ``local`` provider (which walks a single folder in memory every run),
this provider is backed by the persistent :class:`~cinesfx.library.catalog.LibraryCatalog`.
The user first catalogs *all* of their sounds — across as many folders/drives as
they like — with the panel's "Scan library" button or ``run_cli --scan-library``.
Afterwards, placement searches that fast catalog and drops the user's own files
straight onto the timeline (they are already local, so there is no download).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from cinesfx.library.catalog import LibraryCatalog, default_db_path
from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError

_log = get_logger("sound.catalog")


def _roots_from_settings(settings: dict[str, Any]) -> list[str]:
    """Return configured library roots, accepting a list or one string."""
    raw = settings.get("roots")
    if not raw:
        single = settings.get("library_path")
        raw = [single] if single else []
    if isinstance(raw, str):
        # Allow a comma/semicolon/newline-separated string (from the UI field).
        raw = [part.strip() for part in raw.replace(";", ",").replace("\n", ",").split(",")]
    return [str(item) for item in raw if item and str(item).strip()]


class CatalogProvider(SoundProvider):
    """Serve sounds from the user's persistent, self-indexed sound catalog."""

    name = "catalog"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        db_setting = settings.get("db_path")
        db_path = Path(db_setting).expanduser() if db_setting else default_db_path(cache_dir)
        self._catalog = LibraryCatalog(db_path)
        self._roots = _roots_from_settings(settings)
        self._auto_scan = bool(settings.get("auto_scan", False))
        self._probe_duration = bool(settings.get("probe_duration", False))
        self._scanned = False

    @property
    def catalog(self) -> LibraryCatalog:
        return self._catalog

    def scan(self, progress=None):
        """Build/refresh the catalog from the configured roots."""
        if not self._roots:
            raise SoundProviderError(
                "No library folders configured. Set sound_providers.catalog.roots "
                "in config.yaml (or the panel's library folders) to the folder(s) "
                "that hold your sounds."
            )
        return self._catalog.scan(
            self._roots, probe_duration=self._probe_duration, progress=progress
        )

    def _ensure_populated(self) -> None:
        if self._catalog.count() > 0:
            return
        if self._auto_scan and self._roots and not self._scanned:
            self._scanned = True
            _log.info("Catalog empty; auto-scanning %d root(s)…", len(self._roots))
            self.scan()
            if self._catalog.count() > 0:
                return
        raise SoundProviderError(
            "Your sound catalog is empty. Scan your library first — click "
            "'Scan library' in the CineSFX panel, or run: "
            "python -m scripts.run_cli --scan-library"
        )

    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        self._ensure_populated()
        assets: list[SoundAsset] = []
        for entry in self._catalog.search(query, limit=max(1, filters.max_results)):
            assets.append(
                SoundAsset(
                    provider=self.name,
                    asset_id=entry.path,
                    title=entry.stem,
                    duration_seconds=entry.duration,
                    local_path=entry.to_path(),
                    license_name="my library",
                    attribution=entry.category or None,
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        # Catalog files are already on the user's disk; just resolve the path.
        if asset.local_path and asset.local_path.exists():
            return asset.local_path
        path = Path(asset.asset_id)
        if path.exists():
            return path
        raise SoundProviderError(
            f"Cataloged sound no longer exists on disk: {asset.asset_id}. "
            f"Re-scan your library to refresh the catalog."
        )


def build_catalog_provider(settings: dict[str, Any], cache_dir: Path) -> CatalogProvider:
    """Factory helper so the CLI/UI can build a provider from raw settings."""
    return CatalogProvider(settings, cache_dir)


def resolve_catalog_roots(settings: dict[str, Any]) -> list[str]:
    """Expose configured roots (used by diagnostics/CLI reporting)."""
    return _roots_from_settings(settings)
