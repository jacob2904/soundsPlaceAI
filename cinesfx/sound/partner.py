"""Generic partner REST provider for Artlist / Audiio / Musicbed.

None of these platforms publishes an open developer API. Rather than duplicate a
near-identical class per platform, this single provider is parameterised by the
platform name and the environment variables holding its base URL + token. Partners
who have credentials set ``<PLATFORM>_API_BASE`` and ``<PLATFORM>_API_TOKEN`` in
``.env``; without them, the provider raises a clear, actionable error.

The request/response mapping targets a conventional REST shape (a ``/search``
endpoint returning ``{"results": [{id,title,duration,download_url,preview_url}]}``)
and can be adapted per partner via the ``search_path`` / field-name settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import httpx

from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError
from cinesfx.sound.cache import SoundCache

_log = get_logger("sound.partner")

_TIMEOUT = 30.0


class PartnerRestProvider(SoundProvider):
    """A configurable REST client shared by partner sound platforms."""

    def __init__(
        self,
        name: str,
        base_env: str,
        token_env: str,
        settings: dict[str, Any],
        cache_dir: Path,
    ) -> None:
        """Create a partner provider.

        Args:
            name: Provider name (e.g. "artlist").
            base_env: Env var holding the API base URL.
            token_env: Env var holding the bearer token.
            settings: Provider settings from config.
            cache_dir: Cache directory.
        """
        super().__init__(settings, cache_dir)
        self.name = name
        self._cache = SoundCache(cache_dir)
        self._page_size = int(settings.get("page_size", 15))
        self._search_path = str(settings.get("search_path", "/search"))
        self._base_url = AppConfig.secret(base_env)
        self._token = AppConfig.secret(token_env)
        if not self._base_url or not self._token:
            raise SoundProviderError(
                f"{name.capitalize()} has no public developer API. To use it here, "
                f"set {base_env} and {token_env} in your .env with partner "
                f"credentials, or choose a different sound_provider (e.g. 'epidemic', "
                f"'freesound', 'soundly', or 'local')."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }

    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        params = {
            "q": query,
            "type": "sfx",
            "limit": min(self._page_size, max(1, filters.max_results)),
            "sort": filters.sort or "best-match",
        }
        try:
            with httpx.Client(timeout=_TIMEOUT, base_url=self._base_url) as client:
                response = client.get(
                    self._search_path, params=params, headers=self._headers()
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise SoundProviderError(f"{self.name} search failed: {exc}") from exc

        results = payload.get("results", payload) if isinstance(payload, dict) else payload
        assets: list[SoundAsset] = []
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            asset_id = str(item.get("id") or item.get("uuid") or "")
            if not asset_id:
                continue
            assets.append(
                SoundAsset(
                    provider=self.name,
                    asset_id=asset_id,
                    title=str(item.get("title") or item.get("name") or query),
                    duration_seconds=float(item.get("duration", 0.0) or 0.0),
                    preview_url=item.get("preview_url"),
                    download_url=item.get("download_url") or item.get("url"),
                    license_name=self.name,
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        if self._cache.has(self.name, asset.asset_id):
            return self._cache.path_for(self.name, asset.asset_id)
        url = asset.download_url
        if not url:
            url = self._resolve_download_url(asset.asset_id)
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                response = client.get(url, headers=self._headers())
                response.raise_for_status()
                return self._cache.store_bytes(self.name, asset.asset_id, response.content)
        except httpx.HTTPError as exc:
            raise SoundProviderError(
                f"{self.name} download failed for {asset.asset_id}: {exc}"
            ) from exc

    def _resolve_download_url(self, asset_id: str) -> str:
        """Ask the partner API for a temporary download URL for ``asset_id``."""
        try:
            with httpx.Client(timeout=_TIMEOUT, base_url=self._base_url) as client:
                response = client.get(
                    f"/download/{asset_id}", headers=self._headers()
                )
                response.raise_for_status()
                url: Optional[str] = response.json().get("url")
        except httpx.HTTPError as exc:
            raise SoundProviderError(
                f"{self.name} could not resolve a download URL for {asset_id}: {exc}"
            ) from exc
        if not url:
            raise SoundProviderError(
                f"{self.name} returned no download URL for {asset_id}."
            )
        return url
