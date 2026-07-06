"""A persistent, incremental catalog of the user's own sound library.

This is the "index all my sounds" engine. Point it at one or more folders on the
user's computer and it walks them for audio files, extracts light metadata
(name, folder, extension, size, modified-time, optional duration, an inferred
category, and searchable tokens) and stores everything in a small SQLite
database. Re-scanning is **incremental**: unchanged files are skipped, changed
files are refreshed, and files that were deleted on disk are pruned — so keeping
a large library up to date is cheap.

Searching ranks catalog entries against a text query by fast token overlap on
file and folder names (the same matching the ``local`` provider uses), so the AI
brain's abstract cue (e.g. "wooden door creaks open") maps onto the user's real
files. The whole catalog is loaded into memory once per process and cached, so
the many per-cue searches a run performs stay fast even for large libraries.

The database is intentionally a single self-contained file: portable across
Windows/macOS/Linux, safe to delete (just re-scan), and dependency-free beyond
Python's standard-library ``sqlite3``.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from cinesfx.logging_utils import get_logger
from cinesfx.sound.local import _AUDIO_EXTENSIONS, tokenize

_log = get_logger("library.catalog")

_SCHEMA_VERSION = 1

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
    """One cataloged sound file (a row in the catalog)."""

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

    def summary(self) -> str:
        """Return a compact, human-readable one-line summary."""
        return (
            f"{self.total} sound(s) in catalog "
            f"(+{self.added} new, ~{self.updated} updated, -{self.removed} removed, "
            f"{self.skipped} unchanged) in {self.elapsed_seconds:.1f}s"
        )


def default_db_path(cache_dir: Path) -> Path:
    """Return the default catalog database path inside ``cache_dir``."""
    return cache_dir / "library.db"


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
    """A SQLite-backed, incremental catalog of local audio files."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Optional[list[LibraryEntry]] = None
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    # ------------------------------------------------------------------ database

    def _connect(self) -> sqlite3.Connection:
        # A fresh connection per operation keeps the catalog thread-safe: the UI
        # scans on a worker thread while the pipeline searches on its own pool.
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sounds (
                    path      TEXT PRIMARY KEY,
                    filename  TEXT NOT NULL,
                    stem      TEXT NOT NULL,
                    folder    TEXT NOT NULL,
                    ext       TEXT NOT NULL,
                    size      INTEGER NOT NULL,
                    mtime     REAL NOT NULL,
                    duration  REAL NOT NULL DEFAULT 0,
                    category  TEXT NOT NULL DEFAULT '',
                    tags      TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_category ON sounds(category)")
            conn.commit()

    # ---------------------------------------------------------------------- scan

    def scan(
        self,
        roots: Iterable[Path | str],
        *,
        probe_duration: bool = False,
        extensions: Optional[Iterable[str]] = None,
        progress: Optional[Callable[[str], None]] = None,
    ) -> ScanStats:
        """Index (or refresh) every audio file beneath ``roots``.

        Args:
            roots: Folders to walk recursively. Missing folders are skipped.
            probe_duration: When True, read each file's duration (needs the
                optional ``tinytag`` package; otherwise durations stay 0).
            extensions: Audio extensions to include (defaults to the common set).
            progress: Optional callback invoked with short status strings.

        Returns:
            A :class:`ScanStats` describing what changed.
        """
        started = time.monotonic()
        exts = {e.lower() for e in (extensions or _AUDIO_EXTENSIONS)}
        resolved_roots = self._resolve_roots(roots)
        stats = ScanStats(roots=[str(r) for r in resolved_roots])

        if not resolved_roots:
            if progress:
                progress("No valid library folders found to scan.")
            stats.total = self.count()
            stats.elapsed_seconds = time.monotonic() - started
            return stats

        with self._connect() as conn:
            existing = {
                row["path"]: (row["mtime"], row["size"])
                for row in conn.execute("SELECT path, mtime, size FROM sounds")
            }
            seen: set[str] = set()
            pending: list[tuple] = []

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
                    prior = existing.get(key)
                    if prior and prior[0] == stat.st_mtime and prior[1] == stat.st_size:
                        stats.skipped += 1
                        continue
                    pending.append(self._row_for(path, stat, probe_duration))
                    stats.updated += 1 if prior else 0
                    stats.added += 0 if prior else 1
                    if len(pending) >= 500:
                        self._flush(conn, pending)
                        pending.clear()
                        if progress:
                            progress(f"Indexed {stats.scanned} file(s)…")

            self._flush(conn, pending)
            stats.removed = self._prune(conn, resolved_roots, seen)
            conn.commit()
            stats.total = conn.execute("SELECT COUNT(*) FROM sounds").fetchone()[0]

        self._cache = None  # invalidate the in-memory search cache
        stats.elapsed_seconds = time.monotonic() - started
        _log.info("Library scan complete: %s", stats.summary())
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
    def _row_for(path: Path, stat, probe_duration: bool) -> tuple:
        tokens = _entry_tokens(path)
        duration = _probe_duration(path) if probe_duration else 0.0
        return (
            str(path),
            path.name,
            path.stem,
            path.parent.name,
            path.suffix.lower().lstrip("."),
            int(stat.st_size),
            float(stat.st_mtime),
            float(duration),
            infer_category(tokens),
            " ".join(sorted(tokens)),
        )

    @staticmethod
    def _flush(conn: sqlite3.Connection, rows: list[tuple]) -> None:
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO sounds
                (path, filename, stem, folder, ext, size, mtime, duration,
                 category, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename, stem=excluded.stem,
                folder=excluded.folder, ext=excluded.ext, size=excluded.size,
                mtime=excluded.mtime, duration=excluded.duration,
                category=excluded.category, tags=excluded.tags
            """,
            rows,
        )

    @staticmethod
    def _prune(conn: sqlite3.Connection, roots: list[Path], seen: set[str]) -> int:
        """Delete rows under the scanned roots whose files no longer exist."""
        prefixes = [str(root) for root in roots]
        stale: list[str] = []
        for row in conn.execute("SELECT path FROM sounds"):
            path = row["path"]
            if path in seen:
                continue
            if any(path == p or path.startswith(p + "/") or path.startswith(p + "\\")
                   for p in prefixes):
                stale.append(path)
        if stale:
            conn.executemany("DELETE FROM sounds WHERE path = ?", ((p,) for p in stale))
        return len(stale)

    # -------------------------------------------------------------------- search

    def _load_all(self) -> list[LibraryEntry]:
        if self._cache is not None:
            return self._cache
        entries: list[LibraryEntry] = []
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT path, stem, folder, ext, duration, category, tags FROM sounds"
            ):
                tags = row["tags"] or ""
                entries.append(
                    LibraryEntry(
                        path=row["path"],
                        stem=row["stem"],
                        folder=row["folder"],
                        ext=row["ext"],
                        duration=float(row["duration"] or 0.0),
                        category=row["category"] or "",
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
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM sounds").fetchone()[0])

    def stats(self) -> dict:
        """Return counts by category plus a total (for reporting/UI)."""
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM sounds").fetchone()[0])
            by_category = {
                (row["category"] or "uncategorized"): row["n"]
                for row in conn.execute(
                    "SELECT category, COUNT(*) AS n FROM sounds "
                    "GROUP BY category ORDER BY n DESC"
                )
            }
        return {"total": total, "by_category": by_category, "db_path": str(self._db_path)}

    def clear(self) -> None:
        """Remove every entry from the catalog (keeps the empty database)."""
        with self._connect() as conn:
            conn.execute("DELETE FROM sounds")
            conn.commit()
        self._cache = None
