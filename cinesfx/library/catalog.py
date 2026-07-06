"""A persistent, incremental catalog of the user's own sound library.

This is the "index all my sounds" engine. Point it at one or more folders on the
user's computer and it walks them for audio files, extracts light metadata
(name, folder, extension, size, modified-time, optional duration, an inferred
category, and searchable tokens) and stores everything in a single, plain
**JSON file** — no database. The file is human-readable, portable across
Windows/macOS/Linux, safe to delete (just re-scan), and needs nothing beyond
Python's standard library.

Re-scanning is **incremental**: unchanged files are skipped, changed files are
refreshed, and files that were deleted on disk are pruned — so keeping a large
library up to date is cheap.

Searching ranks catalog entries against a text query by fast token overlap on
file and folder names (the same matching the ``local`` provider uses), so the AI
brain's abstract cue (e.g. "wooden door creaks open") maps onto the user's real
files. The whole catalog is loaded into memory once per process and cached, so
the many per-cue searches a run performs stay fast even for large libraries.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from cinesfx.logging_utils import get_logger
from cinesfx.sound.local import _AUDIO_EXTENSIONS, tokenize

_log = get_logger("library.catalog")

_CATALOG_VERSION = 1

# Folder/filename keyword → category. First match wins. Purely a convenience for
# filtering/reporting; matching itself is token-based and category-agnostic.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "footsteps": ("footstep", "footsteps", "foot", "step", "steps", "walk", "run"),
    "door": ("door", "doors", "gate", "hinge"),
    "water": ("water", "rain", "splash", "wave", "waves", "ocean", "river", "drip"),
    "wind": ("wind", "breeze", "gust", "storm"),
    "fire": ("fire", "flame", "burn", "crackle"),
    "impact": ("impact", "hit", "punch", "crash", "slam", "boom", "thud", "smash"),
    "whoosh": ("whoosh", "swoosh", "swish", "transition", "riser", "swell"),
    "ambience": ("ambience", "ambient", "atmos", "room", "background", "bg", "drone"),
    "weapon": ("gun", "gunshot", "sword", "weapon", "shot", "blade", "reload"),
    "vehicle": ("car", "engine", "vehicle", "truck", "motor", "traffic"),
    "animal": ("dog", "cat", "bird", "horse", "animal", "insect", "bark"),
    "ui": ("click", "beep", "ui", "button", "notification", "tick"),
    "voice": ("voice", "crowd", "chatter", "laugh", "scream", "breath"),
}

# How many parent-folder names to fold into the searchable token set. Folder
# names carry a lot of signal in curated libraries (e.g. .../Doors/Wooden/...).
_FOLDER_TOKEN_DEPTH = 4


@dataclass
class LibraryEntry:
    """One cataloged sound file."""

    path: str
    stem: str
    folder: str
    ext: str
    duration: float = 0.0
    category: str = ""
    tokens: frozenset[str] = frozenset()
    score: float = 0.0

    def to_path(self) -> Path:
        return Path(self.path)


@dataclass
class ScanStats:
    """Summary of a scan pass, suitable for logging or UI display."""

    roots: list[str] = field(default_factory=list)
    scanned: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    total: int = 0
    elapsed_seconds: float = 0.0
    dry_run: bool = False

    @property
    def changed(self) -> int:
        """Number of files added, updated, or removed by this pass."""
        return self.added + self.updated + self.removed

    @property
    def in_sync(self) -> bool:
        """True when the catalog already matched the folders (no changes)."""
        return self.changed == 0

    def summary(self) -> str:
        """Return a compact, human-readable one-line summary."""
        if self.in_sync:
            verb = "would be in sync" if self.dry_run else "in sync"
            return f"Library {verb} — {self.total} sound(s), no changes."
        verb = "changes pending" if self.dry_run else "synced"
        return (
            f"Library {verb}: +{self.added} new, ~{self.updated} updated, "
            f"-{self.removed} removed ({self.total} total, "
            f"{self.skipped} unchanged) in {self.elapsed_seconds:.1f}s"
        )


def default_catalog_path(cache_dir: Path) -> Path:
    """Return the default catalog JSON file path inside ``cache_dir``."""
    return cache_dir / "library.json"


def infer_category(tokens: Iterable[str]) -> str:
    """Return a coarse category for a set of tokens ("" if none matches)."""
    token_set = set(tokens)
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if token_set.intersection(keywords):
            return category
    return ""


def _entry_tokens(path: Path) -> set[str]:
    """Return the searchable tokens for ``path`` (name + parent folders)."""
    parts = [path.stem]
    parts.extend(parent.name for parent in list(path.parents)[:_FOLDER_TOKEN_DEPTH])
    return tokenize(" ".join(parts))


def _probe_duration(path: Path) -> float:
    """Best-effort audio duration in seconds (0.0 if it can't be read fast).

    Uses the optional, pure-Python ``tinytag`` package when available (it reads
    header metadata without spawning a process, so it is fast enough to run
    across a whole library). Absent that, duration is left at 0.0 — the real
    length is read from Resolve once the clip is imported, so this is only a
    nice-to-have for reporting/ambience defaults.
    """
    try:  # optional dependency; never required
        from tinytag import TinyTag  # type: ignore
    except Exception:  # noqa: BLE001 - missing/broken tinytag is fine
        return 0.0
    try:
        tag = TinyTag.get(str(path))
        return float(tag.duration or 0.0)
    except Exception:  # noqa: BLE001 - unreadable/odd files must not stop a scan
        return 0.0


class LibraryCatalog:
    """A JSON-file-backed, incremental catalog of local audio files.

    The on-disk format is a single JSON object::

        {"version": 1, "sounds": {"<abs path>": {stem, folder, ext, size,
                                                  mtime, duration, category, tags}}}

    Keying by absolute path makes incremental re-scans a simple dict update.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[list[LibraryEntry]] = None

    @property
    def catalog_path(self) -> Path:
        return self._path

    # ------------------------------------------------------------------ file I/O

    def _read_raw(self) -> dict[str, dict[str, Any]]:
        """Return the ``sounds`` mapping from disk (``{}`` if missing/invalid)."""
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("Could not read catalog %s: %s", self._path, exc)
            return {}
        sounds = data.get("sounds") if isinstance(data, dict) else None
        return sounds if isinstance(sounds, dict) else {}

    def _write_raw(self, sounds: dict[str, dict[str, Any]]) -> None:
        """Atomically write the ``sounds`` mapping to disk (compact JSON)."""
        payload = {"version": _CATALOG_VERSION, "sounds": sounds}
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"))
        tmp.replace(self._path)

    # ---------------------------------------------------------------------- scan

    def scan(
        self,
        roots: Iterable[Path | str],
        *,
        probe_duration: bool = False,
        extensions: Optional[Iterable[str]] = None,
        progress: Optional[Callable[[str], None]] = None,
        dry_run: bool = False,
    ) -> ScanStats:
        """Index or **resync** every audio file beneath ``roots``.

        This is fully incremental, so calling it again after files change on disk
        is a resync: new files are added, modified files are refreshed, and files
        that were deleted are pruned.

        Args:
            roots: Folders to walk recursively. Missing folders are skipped.
            probe_duration: When True, read each file's duration (needs the
                optional ``tinytag`` package; otherwise durations stay 0).
            extensions: Audio extensions to include (defaults to the common set).
            progress: Optional callback invoked with short status strings.
            dry_run: When True, only *detect* what would change (added/updated/
                removed) without writing the catalog — used to tell the user
                whether a resync is needed.

        Returns:
            A :class:`ScanStats` describing what changed (or would change).
        """
        started = time.monotonic()
        exts = {e.lower() for e in (extensions or _AUDIO_EXTENSIONS)}
        resolved_roots = self._resolve_roots(roots)
        stats = ScanStats(roots=[str(r) for r in resolved_roots], dry_run=dry_run)

        if not resolved_roots:
            if progress:
                progress("No valid library folders found to scan.")
            stats.total = self.count()
            stats.elapsed_seconds = time.monotonic() - started
            return stats

        sounds = self._read_raw()
        seen: set[str] = set()

        for root in resolved_roots:
            if progress:
                progress(f"Scanning {root}…")
            for path in self._walk_audio(root, exts):
                key = str(path)
                seen.add(key)
                stats.scanned += 1
                try:
                    stat = path.stat()
                except OSError:
                    continue
                prior = sounds.get(key)
                if (
                    prior
                    and prior.get("mtime") == stat.st_mtime
                    and prior.get("size") == stat.st_size
                ):
                    stats.skipped += 1
                    continue
                # Skip the (slower) duration probe when only detecting changes.
                sounds[key] = self._entry_dict(
                    path, stat, probe_duration and not dry_run
                )
                stats.updated += 1 if prior else 0
                stats.added += 0 if prior else 1
                if progress and stats.scanned % 500 == 0:
                    progress(f"Indexed {stats.scanned} file(s)…")

        stats.removed = self._prune(sounds, resolved_roots, seen)
        stats.total = len(sounds)

        if not dry_run:
            self._write_raw(sounds)
            self._cache = None  # invalidate the in-memory search cache

        stats.elapsed_seconds = time.monotonic() - started
        _log.info(
            "Library %s complete: %s",
            "change check" if dry_run else "scan",
            stats.summary(),
        )
        if progress:
            progress(stats.summary())
        return stats

    @staticmethod
    def _resolve_roots(roots: Iterable[Path | str]) -> list[Path]:
        resolved: list[Path] = []
        for raw in roots:
            if not raw:
                continue
            path = Path(str(raw)).expanduser()
            if path.is_dir():
                resolved.append(path)
            else:
                _log.warning("Skipping missing library folder: %s", path)
        return resolved

    @staticmethod
    def _walk_audio(root: Path, exts: set[str]) -> Iterable[Path]:
        for path in root.rglob("*"):
            try:
                if path.is_file() and path.suffix.lower() in exts:
                    yield path
            except OSError:  # unreadable entries (permissions, broken links)
                continue

    @staticmethod
    def _entry_dict(path: Path, stat: Any, probe_duration: bool) -> dict[str, Any]:
        tokens = _entry_tokens(path)
        duration = _probe_duration(path) if probe_duration else 0.0
        return {
            "stem": path.stem,
            "folder": path.parent.name,
            "ext": path.suffix.lower().lstrip("."),
            "size": int(stat.st_size),
            "mtime": float(stat.st_mtime),
            "duration": float(duration),
            "category": infer_category(tokens),
            "tags": " ".join(sorted(tokens)),
        }

    @staticmethod
    def _prune(
        sounds: dict[str, dict[str, Any]], roots: list[Path], seen: set[str]
    ) -> int:
        """Drop entries under the scanned roots whose files no longer exist."""
        prefixes = [str(root) for root in roots]
        stale = [
            key
            for key in sounds
            if key not in seen
            and any(
                key == p or key.startswith(p + "/") or key.startswith(p + "\\")
                for p in prefixes
            )
        ]
        for key in stale:
            del sounds[key]
        return len(stale)

    # -------------------------------------------------------------------- search

    def _load_all(self) -> list[LibraryEntry]:
        if self._cache is not None:
            return self._cache
        entries: list[LibraryEntry] = []
        for path, row in self._read_raw().items():
            tags = row.get("tags") or ""
            entries.append(
                LibraryEntry(
                    path=path,
                    stem=row.get("stem", Path(path).stem),
                    folder=row.get("folder", ""),
                    ext=row.get("ext", ""),
                    duration=float(row.get("duration", 0.0) or 0.0),
                    category=row.get("category", "") or "",
                    tokens=frozenset(tags.split()) if tags else frozenset(),
                )
            )
        self._cache = entries
        return entries

    def search(
        self, query: str, limit: int = 10, category: Optional[str] = None
    ) -> list[LibraryEntry]:
        """Return the best ``limit`` matches for ``query`` (best first).

        Ranking is token overlap between the query and each file's name/folder
        tokens, with a small boost when the file's inferred category matches the
        query and a tie-break toward shorter (more specific) names.
        """
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scored: list[LibraryEntry] = []
        for entry in self._load_all():
            if not entry.tokens:
                continue
            overlap = query_tokens & entry.tokens
            if not overlap:
                continue
            score = len(overlap) / len(query_tokens)
            if category and entry.category == category:
                score += 0.15
            elif entry.category and entry.category in query_tokens:
                score += 0.1
            scored.append(
                LibraryEntry(
                    path=entry.path,
                    stem=entry.stem,
                    folder=entry.folder,
                    ext=entry.ext,
                    duration=entry.duration,
                    category=entry.category,
                    tokens=entry.tokens,
                    score=score,
                )
            )

        scored.sort(key=lambda e: (e.score, -len(e.stem)), reverse=True)
        return scored[: max(1, limit)]

    # --------------------------------------------------------------------- stats

    def count(self) -> int:
        """Return the number of cataloged sounds."""
        return len(self._load_all())

    def stats(self) -> dict[str, Any]:
        """Return counts by category plus a total (for reporting/UI)."""
        by_category: dict[str, int] = {}
        for entry in self._load_all():
            key = entry.category or "uncategorized"
            by_category[key] = by_category.get(key, 0) + 1
        ordered = dict(
            sorted(by_category.items(), key=lambda item: item[1], reverse=True)
        )
        return {
            "total": len(self._load_all()),
            "by_category": ordered,
            "path": str(self._path),
        }

    def clear(self) -> None:
        """Remove every entry from the catalog (writes an empty catalog file)."""
        self._write_raw({})
        self._cache = None
