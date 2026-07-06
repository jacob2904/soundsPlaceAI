"""Tests for the user sound-library catalog and the catalog provider."""

import pytest

from cinesfx.library.catalog import LibraryCatalog, infer_category
from cinesfx.sound.base import SearchFilters, SoundProviderError
from cinesfx.sound.catalog import CatalogProvider


def _make_library(root):
    """Create a small, realistic sound-library tree under ``root``."""
    (root / "Doors" / "Wooden").mkdir(parents=True)
    (root / "Footsteps" / "Gravel").mkdir(parents=True)
    (root / "Doors" / "Wooden" / "door_creak_open_slow.wav").write_bytes(b"x")
    (root / "Doors" / "wooden_door_slam.wav").write_bytes(b"x")
    (root / "Footsteps" / "Gravel" / "run_gravel_01.wav").write_bytes(b"x")
    (root / "notes.txt").write_text("not audio")  # ignored


# --------------------------------------------------------------------- catalog


def test_scan_indexes_only_audio(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")

    stats = catalog.scan([lib])
    assert stats.added == 3
    assert stats.total == 3
    assert catalog.count() == 3


def test_search_matches_by_name_and_folder(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])

    results = catalog.search("wooden door creaks open", limit=5)
    assert results
    assert results[0].stem == "door_creak_open_slow"

    footsteps = catalog.search("gravel footsteps running", limit=5)
    assert footsteps[0].stem == "run_gravel_01"


def test_search_empty_query_returns_nothing(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])
    assert catalog.search("   ", limit=5) == []


def test_scan_is_incremental(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])

    # Re-scan with no changes: everything is skipped, nothing added.
    again = catalog.scan([lib])
    assert again.added == 0
    assert again.updated == 0
    assert again.skipped == 3
    assert again.total == 3


def test_scan_prunes_deleted_files(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])

    (lib / "Doors" / "wooden_door_slam.wav").unlink()
    stats = catalog.scan([lib])
    assert stats.removed == 1
    assert catalog.count() == 2


def test_dry_run_detects_changes_without_writing(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)  # 3 audio files
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])
    assert catalog.count() == 3

    # Change on disk: add one, modify one (size change), delete one.
    (lib / "new_whoosh.wav").write_bytes(b"x")
    (lib / "Doors" / "wooden_door_slam.wav").write_bytes(b"xxxx")
    (lib / "Footsteps" / "Gravel" / "run_gravel_01.wav").unlink()

    diff = catalog.scan([lib], dry_run=True)
    assert diff.dry_run is True
    assert diff.added == 1
    assert diff.updated == 1
    assert diff.removed == 1
    assert diff.changed == 3
    assert diff.in_sync is False
    # Nothing was written — the catalog still reflects the original 3 files.
    assert catalog.count() == 3

    # Applying the resync writes the changes (+1 added, -1 removed => 3).
    applied = catalog.scan([lib])
    assert applied.in_sync is False
    assert catalog.count() == 3


def test_dry_run_reports_in_sync_when_unchanged(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])

    diff = catalog.scan([lib], dry_run=True)
    assert diff.in_sync is True
    assert diff.changed == 0
    assert diff.skipped == 3


def test_scan_multiple_roots(tmp_path):
    lib_a = tmp_path / "a"
    lib_b = tmp_path / "b"
    lib_a.mkdir()
    lib_b.mkdir()
    (lib_a / "thunder.wav").write_bytes(b"x")
    (lib_b / "rain.wav").write_bytes(b"x")
    catalog = LibraryCatalog(tmp_path / "catalog.json")

    stats = catalog.scan([lib_a, lib_b])
    assert stats.total == 2
    assert catalog.search("thunder", limit=3)[0].stem == "thunder"
    assert catalog.search("rain", limit=3)[0].stem == "rain"


def test_scanning_one_root_does_not_prune_another(tmp_path):
    lib_a = tmp_path / "a"
    lib_b = tmp_path / "b"
    lib_a.mkdir()
    lib_b.mkdir()
    (lib_a / "one.wav").write_bytes(b"x")
    (lib_b / "two.wav").write_bytes(b"x")
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib_a, lib_b])

    # Re-scanning only root A must not delete B's entries.
    catalog.scan([lib_a])
    assert catalog.count() == 2


def test_stats_report_categories(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])
    info = catalog.stats()
    assert info["total"] == 3
    assert "door" in info["by_category"]


def test_clear_empties_catalog(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    catalog = LibraryCatalog(tmp_path / "catalog.json")
    catalog.scan([lib])
    catalog.clear()
    assert catalog.count() == 0


def test_infer_category():
    assert infer_category({"door", "creak"}) == "door"
    assert infer_category({"footstep", "gravel"}) == "footsteps"
    assert infer_category({"unknownword"}) == ""


# -------------------------------------------------------------------- provider


def test_catalog_provider_search_and_download(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    provider = CatalogProvider(
        {"roots": [str(lib)]}, cache_dir=tmp_path / "cache"
    )
    provider.scan()

    results = provider.search("door creak", SearchFilters(max_results=3))
    assert results
    assert results[0].provider == "catalog"
    assert provider.download(results[0]).exists()


def test_catalog_provider_resync_picks_up_changes(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    provider = CatalogProvider({"roots": [str(lib)]}, cache_dir=tmp_path / "cache")
    provider.scan()
    assert provider.catalog.count() == 3

    (lib / "extra_boom.wav").write_bytes(b"x")

    # Dry-run detects the change without writing.
    diff = provider.scan(dry_run=True)
    assert diff.added == 1
    assert diff.in_sync is False
    assert provider.catalog.count() == 3

    # Real resync applies it and it becomes searchable.
    provider.scan()
    assert provider.catalog.count() == 4
    assert provider.search("boom", SearchFilters(max_results=3))


def test_catalog_provider_empty_errors(tmp_path):
    provider = CatalogProvider(
        {"roots": [str(tmp_path / "lib")]}, cache_dir=tmp_path / "cache"
    )
    (tmp_path / "lib").mkdir()
    with pytest.raises(SoundProviderError):
        provider.search("door", SearchFilters())


def test_catalog_provider_requires_roots_to_scan(tmp_path):
    provider = CatalogProvider({}, cache_dir=tmp_path / "cache")
    with pytest.raises(SoundProviderError):
        provider.scan()


def test_catalog_provider_auto_scan(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    provider = CatalogProvider(
        {"roots": [str(lib)], "auto_scan": True}, cache_dir=tmp_path / "cache"
    )
    # No explicit scan(): first search auto-indexes because auto_scan is on.
    results = provider.search("gravel run", SearchFilters(max_results=3))
    assert results


def test_catalog_provider_accepts_comma_separated_roots(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    provider = CatalogProvider(
        {"roots": f"{lib}, {tmp_path / 'missing'}"}, cache_dir=tmp_path / "cache"
    )
    stats = provider.scan()
    assert stats.total == 3


def test_catalog_provider_missing_file_download_errors(tmp_path):
    lib = tmp_path / "lib"
    _make_library(lib)
    provider = CatalogProvider({"roots": [str(lib)]}, cache_dir=tmp_path / "cache")
    provider.scan()
    results = provider.search("door creak", SearchFilters(max_results=1))
    asset = results[0]
    asset.local_path.unlink()
    with pytest.raises(SoundProviderError):
        provider.download(asset)
