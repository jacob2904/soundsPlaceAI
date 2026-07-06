"""Content-addressed cache for downloaded sound-effect files."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cinesfx.logging_utils import get_logger

_log = get_logger("sound.cache")


class SoundCache:
    """Stores downloaded audio keyed by provider + asset id.

    A cached file is reused across runs so the same effect is only ever fetched
    once, which keeps the pipeline fast and reduces API usage.
    """

    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir / "sounds"
        self._dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, provider: str, asset_id: str, extension: str = "mp3") -> Path:
        """Return the deterministic cache path for an asset."""
        digest = hashlib.sha1(f"{provider}:{asset_id}".encode("utf-8")).hexdigest()[:20]
        safe_ext = extension.lstrip(".") or "mp3"
        return self._dir / f"{provider}_{digest}.{safe_ext}"

    def has(self, provider: str, asset_id: str, extension: str = "mp3") -> bool:
        """Return True if a non-empty cached file already exists."""
        path = self.path_for(provider, asset_id, extension)
        return path.exists() and path.stat().st_size > 0

    def store_bytes(
        self, provider: str, asset_id: str, data: bytes, extension: str = "mp3"
    ) -> Path:
        """Write ``data`` to the cache and return its path."""
        path = self.path_for(provider, asset_id, extension)
        path.write_bytes(data)
        _log.debug("Cached %s bytes for %s/%s", len(data), provider, asset_id)
        return path
