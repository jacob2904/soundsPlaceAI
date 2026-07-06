"""Tests for the content-addressed sound cache and local indexing."""

from cinesfx.sound.cache import SoundCache
from cinesfx.sound.local import LocalLibraryIndex, tokenize


def test_cache_roundtrip(tmp_path):
    cache = SoundCache(tmp_path)
    assert not cache.has("epidemic", "abc")
    path = cache.store_bytes("epidemic", "abc", b"data")
    assert path.exists()
    assert cache.has("epidemic", "abc")
    # Deterministic path for the same key.
    assert cache.path_for("epidemic", "abc") == path


def test_cache_keys_are_distinct(tmp_path):
    cache = SoundCache(tmp_path)
    a = cache.path_for("epidemic", "one")
    b = cache.path_for("epidemic", "two")
    c = cache.path_for("freesound", "one")
    assert a != b != c and a != c


def test_tokenize_splits_on_non_alnum():
    assert tokenize("Wooden_Door-Creak 01") == {"wooden", "door", "creak", "01"}


def test_local_index_ranks_by_overlap(tmp_path):
    (tmp_path / "doors").mkdir()
    (tmp_path / "doors" / "wooden_door_creak.wav").write_bytes(b"x")
    (tmp_path / "footstep_gravel.wav").write_bytes(b"x")
    index = LocalLibraryIndex(tmp_path)

    ranked = index.rank("wooden door creak", limit=5)
    assert ranked
    assert ranked[0][0].name == "wooden_door_creak.wav"

    none = index.rank("spaceship laser", limit=5)
    assert none == []
