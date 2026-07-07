"""Freesound provider — free, public API fallback.

Freesound (https://freesound.org) offers an open API with a free key. Great as a
zero-cost default so the pipeline is fully runnable without a paid partnership.
Note: results are Creative Commons; attribution requirements vary per sound.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError
from cinesfx.sound.cache import SoundCache

_log = get_logger("sound.freesound")

_API_BASE = "https://freesound.org/apiv2"
_TIMEOUT = 30.0


class FreesoundProvider(SoundProvider):
    """Search and download sounds from Freesound's public API."""

    name = "freesound"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        self._cache = SoundCache(cache_dir)
        self._page_size = int(settings.get("page_size", 15))
        self._api_key = AppConfig.secret("FREESOUND_API_KEY")
        if not self._api_key:
            raise SoundProviderError(
                "FREESOUND_API_KEY is not set. Get a free key at "
                "https://freesound.org/apiv2/apply/ and add it to your .env."
            )

    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        params: dict[str, Any] = {
            "query": query,
            "page_size": min(self._page_size, max(1, filters.max_results)),
            "fields": "id,name,duration,previews,license,username",
            "token": self._api_key,
        }
        if filters.max_duration_seconds > 0:
            params["filter"] = f"duration:[0 TO {filters.max_duration_seconds:.1f}]"
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.get(f"{_API_BASE}/search/text/", params=params)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise SoundProviderError(f"Freesound search failed: {exc}") from exc

        assets: list[SoundAsset] = []
        for item in payload.get("results", []):
            previews = item.get("previews", {}) or {}
            preview_url = (
                previews.get("preview-hq-mp3")
                or previews.get("preview-lq-mp3")
                or None
            )
            assets.append(
                SoundAsset(
                    provider=self.name,
                    asset_id=str(item.get("id")),
                    title=str(item.get("name", query)),
                    duration_seconds=float(item.get("duration", 0.0) or 0.0),
                    preview_url=preview_url,
                    download_url=preview_url,
                    attribution=str(item.get("username", "")),
                    license_name=str(item.get("license", "")),
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        if self._cache.has(self.name, asset.asset_id):
            return self._cache.path_for(self.name, asset.asset_id)
        # The full-quality download endpoint needs OAuth2; the high-quality MP3
        # preview is available with the token alone and is ideal for SFX use.
        url = asset.download_url or asset.preview_url
        if not url:
            raise SoundProviderError(
                f"Freesound asset {asset.asset_id} has no downloadable preview URL."
            )
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url, params={"token": self._api_key})
                response.raise_for_status()
                return self._cache.store_bytes(self.name, asset.asset_id, response.content)
        except httpx.HTTPError as exc:
            raise SoundProviderError(
                f"Freesound download failed for {asset.asset_id}: {exc}"
            ) from exc
