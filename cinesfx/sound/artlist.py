"""Artlist provider — official Artlist Enterprise API (OAuth 2.0).

Artlist publishes a real Enterprise API (https://developer.artlist.io) using the
OAuth 2.0 Client Credentials flow. Credentials (``client_id`` / ``client_secret``)
are issued by an Artlist account manager.

Important honesty note: at the time of writing the Enterprise API's search +
download endpoints officially support the ``song`` asset type (music). Artlist's
catalogue includes sound effects, but SFX are not yet exposed through the public
API. This provider is implemented against the documented endpoints and exposes an
``asset_type`` setting (default ``song``) so it will work for SFX the moment
Artlist enables that asset type — without any code change.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from cinesfx.config import AppConfig
from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError
from cinesfx.sound.cache import SoundCache

_log = get_logger("sound.artlist")

_TOKEN_URL = "https://artlist-business-api-prod-cognito.artlist.io/oauth2/token"
_API_BASE = "https://business.artlist.io"
_TIMEOUT = 30.0
_TOKEN_SAFETY_WINDOW = 60  # refresh a minute before expiry


class ArtlistProvider(SoundProvider):
    """Search and download from the Artlist Enterprise API."""

    name = "artlist"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        self._cache = SoundCache(cache_dir)
        self._page_size = int(settings.get("page_size", 20))
        self._asset_type = str(settings.get("asset_type", "song"))
        self._format = str(settings.get("format", "aac")).lower()
        self._token_url = str(settings.get("token_url", _TOKEN_URL))
        self._api_base = str(settings.get("api_base", _API_BASE)).rstrip("/")
        self._client_id = AppConfig.secret("ARTLIST_CLIENT_ID")
        self._client_secret = AppConfig.secret("ARTLIST_CLIENT_SECRET")
        if not self._client_id or not self._client_secret:
            raise SoundProviderError(
                "Artlist needs ARTLIST_CLIENT_ID and ARTLIST_CLIENT_SECRET in your "
                ".env (issued by your Artlist account manager). Note: the Artlist "
                "API currently serves music; SFX support depends on Artlist enabling "
                "it. Use 'epidemic', 'freesound', 'soundly', 'splice', or 'local' "
                "for sound effects today."
            )
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------ auth

    def _access_token(self) -> str:
        """Return a cached OAuth token, refreshing it when near expiry."""
        if self._token and time.monotonic() < self._token_expiry:
            return self._token

        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode("utf-8")
        ).decode("ascii")
        try:
            with httpx.Client(timeout=_TIMEOUT) as client:
                response = client.post(
                    self._token_url,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": f"Basic {basic}",
                    },
                    data={"grant_type": "client_credentials"},
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise SoundProviderError(f"Artlist authentication failed: {exc}") from exc

        token = payload.get("access_token")
        if not token:
            raise SoundProviderError("Artlist token response contained no access_token.")
        expires_in = float(payload.get("expires_in", 3600))
        self._token = token
        self._token_expiry = time.monotonic() + max(0.0, expires_in - _TOKEN_SAFETY_WINDOW)
        return token

    def _auth_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Authorization": f"Bearer {self._access_token()}"}

    # ------------------------------------------------------------------ search

    def search(self, query: str, filters: SearchFilters) -> list[SoundAsset]:
        params = {
            "page": 1,
            "query": query,
            "pageSize": min(self._page_size, max(1, filters.max_results)),
        }
        try:
            with httpx.Client(timeout=_TIMEOUT, base_url=self._api_base) as client:
                response = client.get(
                    "/search/v1/song", params=params, headers=self._auth_headers()
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPError as exc:
            raise SoundProviderError(f"Artlist search failed: {exc}") from exc

        assets: list[SoundAsset] = []
        for item in _iter_songs(payload):
            asset_id = _first_value(item, ("id", "songId", "sptId", "uuid"))
            if not asset_id:
                continue
            artist = item.get("artist") or {}
            assets.append(
                SoundAsset(
                    provider=self.name,
                    asset_id=str(asset_id),
                    title=str(item.get("name") or query),
                    duration_seconds=float(item.get("duration", 0.0) or 0.0),
                    preview_url=item.get("waveSurferUrl") or item.get("url"),
                    attribution=str(artist.get("name", "")) if isinstance(artist, dict) else "",
                    license_name="Artlist",
                )
            )
        return assets

    # ------------------------------------------------------------------ download

    def download(self, asset: SoundAsset) -> Path:
        extension = "wav" if self._format == "wav" else "mp3" if self._format == "mp3" else "aac"
        if self._cache.has(self.name, asset.asset_id, extension):
            return self._cache.path_for(self.name, asset.asset_id, extension)

        cdn_url = self._downloadable_url(asset.asset_id)
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                audio = client.get(cdn_url)
                audio.raise_for_status()
                return self._cache.store_bytes(
                    self.name, asset.asset_id, audio.content, extension
                )
        except httpx.HTTPError as exc:
            raise SoundProviderError(
                f"Artlist download failed for {asset.asset_id}: {exc}"
            ) from exc

    def _downloadable_url(self, asset_id: str) -> str:
        """Resolve a temporary CDN download URL for an asset."""
        path = f"/download/v1/downloadable/{self._asset_type}/{asset_id}/{self._format}"
        try:
            with httpx.Client(timeout=_TIMEOUT, base_url=self._api_base) as client:
                response = client.get(path, headers=self._auth_headers())
                response.raise_for_status()
                url = response.json().get("url")
        except httpx.HTTPError as exc:
            raise SoundProviderError(
                f"Artlist could not resolve a download URL for {asset_id}: {exc}"
            ) from exc
        if not url:
            raise SoundProviderError(f"Artlist returned no download URL for {asset_id}.")
        return url


def _iter_songs(payload: Any) -> list[dict[str, Any]]:
    """Return the list of song dicts from various response shapes."""
    if isinstance(payload, dict):
        for key in ("songs", "items", "results", "data", "content"):
            value = payload.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
    if isinstance(payload, list):
        return [entry for entry in payload if isinstance(entry, dict)]
    return []


def _first_value(item: dict[str, Any], keys: tuple[str, ...]) -> Optional[Any]:
    """Return the first present, truthy value among ``keys``."""
    for key in keys:
        value = item.get(key)
        if value:
            return value
    return None
