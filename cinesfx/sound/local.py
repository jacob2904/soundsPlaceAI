"""Local-folder sound provider + reusable filename keyword matcher.

Indexes a directory of audio files and ranks them against a query by simple,
fast token overlap on file names and parent folder names. This powers both the
generic ``local`` provider and the ``soundly`` provider (which points at a local
Soundly library folder).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from cinesfx.logging_utils import get_logger
from cinesfx.models import SoundAsset
from cinesfx.sound.base import SearchFilters, SoundProvider, SoundProviderError

_log = get_logger("sound.local")

_AUDIO_EXTENSIONS = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".ogg", ".m4a"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> set[str]:
    """Return the lowercase alphanumeric tokens in ``text``."""
    return set(_TOKEN_RE.findall(text.lower()))


class LocalLibraryIndex:
    """A lightweight, in-memory index over an audio folder tree."""

    def __init__(self, root: Path) -> None:
        if not root.exists() or not root.is_dir():
            raise SoundProviderError(
                f"Sound library folder does not exist: {root}. Set the correct "
                f"'library_path' in config.yaml."
            )
        self._root = root
        self._files: list[Path] = [
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in _AUDIO_EXTENSIONS
        ]
        _log.info("Indexed %d audio file(s) under %s", len(self._files), root)

    def rank(self, query: str, limit: int) -> list[tuple[Path, float]]:
        """Return the top ``limit`` (path, score) matches for ``query``."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[Path, float]] = []
        for path in self._files:
            # Match against the file name and its immediate folders for context.
            haystack = f"{path.parent.name} {path.stem}"
            file_tokens = tokenize(haystack)
            if not file_tokens:
                continue
            overlap = query_tokens & file_tokens
            if not overlap:
                continue
            score = len(overlap) / len(query_tokens)
            scored.append((path, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


class LocalFolderProvider(SoundProvider):
    """Serve sound effects from a local folder of audio files."""

    name = "local"

    def __init__(self, settings: dict[str, Any], cache_dir: Path) -> None:
        super().__init__(settings, cache_dir)
        self._index = LocalLibraryIndex(_require_library_path(settings))

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
                    license_name="local",
                )
            )
        return assets

    def download(self, asset: SoundAsset) -> Path:
        # Files are already local; just return the path.
        if asset.local_path and asset.local_path.exists():
            return asset.local_path
        path = Path(asset.asset_id)
        if path.exists():
            return path
        raise SoundProviderError(f"Local sound file not found: {asset.asset_id}")


def _require_library_path(settings: dict[str, Any]) -> Path:
    """Extract and validate the ``library_path`` from provider settings."""
    raw: Optional[str] = settings.get("library_path")
    if not raw:
        raise SoundProviderError(
            "No 'library_path' configured for the local sound provider. Set it in "
            "config.yaml (sound_providers.local.library_path)."
        )
    return Path(raw).expanduser()
