"""User sound-library cataloging.

Tools for scanning a user's own computer for audio files, storing them in a fast
persistent catalog, and searching that catalog so the pipeline can place the
user's *own* sounds onto the Resolve timeline.
"""

from cinesfx.library.catalog import (
    LibraryCatalog,
    LibraryEntry,
    ScanStats,
    default_catalog_path,
)

__all__ = [
    "LibraryCatalog",
    "LibraryEntry",
    "ScanStats",
    "default_catalog_path",
]
