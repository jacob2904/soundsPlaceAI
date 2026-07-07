"""Epidemic Sound provider — Partner Content API (sound effects).

Implements search + download against the documented Epidemic Sound Partner Content
API. Requires a partnership agreement and an API key (bearer token). See:
https://developers.epidemicsound.com/docs/sound-effects/
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

_log = get_logger("sound.epidemic")

_API_BASE = "https://partner-content-api.epidemicsound.com/v0"
_TIMEOUT = 30.0


class EpidemicSoundProvider(SoundProvider):
    """Search and download sound effects from Epidemic Sound."""

    name = "epidemic"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        self._cache = SoundCache(cache_dir)
        self._quality = str(settings.get("quality", "high")).lower()
        self._api_key = AppConfig.secret("EPIDEMIC_API_KEY")
        if not self._api_key:
            raise SoundProviderError(
                "EPIDEMIC_API_KEY is not set. Add it to your .env (requires an "
                "Epidemic Sound partnership)."
            )
        self._partner_user_id = AppConfig.secret("EPIDEMIC_PARTNER_USER_ID")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        if self._partner_user_id:
            headers["x-partner-user-id"] = self._partner_user_id
        return headers

    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        params = {
            "term": query,
            "limit": min(60, max(1, filters.max_results)),
            "sort": filters.sort or "best-match",
            "order": "desc",
        }
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.get(
                    f"{_API_BASE}/sound-effects/search",
                    params=params,
                    headers=self._headers(),
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise SoundProviderError(f"Epidemic Sound search failed: {exc}") from exc

        assets: list[SoundAsset] = []
        for item in _iter_items(payload):
            asset_id = str(item.get("id") or item.get("trackId") or "")
            if not asset_id:
                continue
            assets.append(
                SoundAsset(
                    provider=self.name,
                    asset_id=asset_id,
                    title=str(item.get("title") or item.get("name") or query),
                    duration_seconds=float(item.get("length") or item.get("duration") or 0.0),
                    preview_url=_first_url(item.get("previews")),
                    license_name="Epidemic Sound",
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        if self._cache.has(self.name, asset.asset_id):
            return self._cache.path_for(self.name, asset.asset_id)

        quality = "high" if self._quality == "high" else "normal"
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                meta = client.get(
                    f"{_API_BASE}/sound-effects/{asset.asset_id}/download",
                    params={"format": "mp3", "quality": quality},
                    headers=self._headers(),
                )
                meta.raise_for_status()
                cdn_url = meta.json().get("url")
                if not cdn_url:
                    raise SoundProviderError(
                        f"Epidemic Sound returned no download URL for {asset.asset_id}."
                    )
                audio = client.get(cdn_url)
                audio.raise_for_status()
                return self._cache.store_bytes(self.name, asset.asset_id, audio.content)
        except httpx.HTTPError as exc:
            raise SoundProviderError(
                f"Epidemic Sound download failed for {asset.asset_id}: {exc}"
            ) from exc


def _iter_items(payload: Any) -> list[dict[str, Any]]:
    """Return the list of result dicts from various possible response shapes."""
    if isinstance(payload, dict):
        for key in ("soundEffects", "items", "results", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    return []


def _first_url(previews: Any) -> str | None:
    """Extract a preview URL from a variety of preview payload shapes."""
    if isinstance(previews, dict):
        for value in previews.values():
            if isinstance(value, str) and value.startswith("http"):
                return value
    if isinstance(previews, list):
        for entry in previews:
            if isinstance(entry, str) and entry.startswith("http"):
                return entry
            if isinstance(entry, dict):
                url = entry.get("url")
                if isinstance(url, str):
                    return url
    return None
