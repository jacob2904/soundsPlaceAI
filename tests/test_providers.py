"""Tests for the Splice (local) and Artlist (Enterprise API) providers."""

import httpx
import pytest

from cinesfx.sound.artlist import ArtlistProvider
from cinesfx.sound.base import SearchFilters, SoundProviderError
from cinesfx.sound.splice import SpliceProvider, resolve_splice_library


# --------------------------------------------------------------------- Splice


def test_splice_indexes_local_folder(tmp_path):
    lib = tmp_path / "Splice"
    (lib / "fx").mkdir(parents=True)
    (lib / "fx" / "laser_zap.wav").write_bytes(b"x")
    (lib / "kick_punch.wav").write_bytes(b"x")

    provider = SpliceProvider({"library_path": str(lib)}, cache_dir=tmp_path / "cache")
    results = provider.search("laser zap", SearchFilters(max_results=5))
    assert results
    assert results[0].title == "laser_zap"
    # Local files resolve directly (no network download).
    assert provider.download(results[0]).exists()


def test_splice_autodetects_default_path(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    (tmp_path / "Splice").mkdir()
    resolved = resolve_splice_library(None)
    assert resolved == tmp_path / "Splice"


def test_splice_missing_folder_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "empty")
    with pytest.raises(SoundProviderError):
        resolve_splice_library(None)


# --------------------------------------------------------------------- Artlist


def _artlist_with_mock(tmp_path, handler):
    """Build an ArtlistProvider whose httpx calls hit a mock transport."""
    provider = ArtlistProvider(
        {"asset_type": "song", "format": "mp3"}, cache_dir=tmp_path / "cache"
    )
    transport = httpx.MockTransport(handler)

    real_client = httpx.Client

    def _client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    return provider, _client


def test_artlist_requires_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("ARTLIST_CLIENT_ID", raising=False)
    monkeypatch.delenv("ARTLIST_CLIENT_SECRET", raising=False)
    with pytest.raises(SoundProviderError):
        ArtlistProvider({}, cache_dir=tmp_path / "cache")


def test_artlist_search_and_download(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTLIST_CLIENT_ID", "id123")
    monkeypatch.setenv("ARTLIST_CLIENT_SECRET", "secret456")

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if "/search/v1/song" in url:
            return httpx.Response(
                200,
                json={
                    "songs": [
                        {
                            "id": "song-1",
                            "name": "Distant Thunder",
                            "duration": 12.0,
                            "artist": {"name": "ACME"},
                            "waveSurferUrl": "https://cdn/wave",
                        }
                    ]
                },
            )
        if "/download/v1/downloadable/" in url:
            return httpx.Response(200, json={"url": "https://cdn/audio.mp3"})
        if url == "https://cdn/audio.mp3":
            return httpx.Response(200, content=b"AUDIODATA")
        return httpx.Response(404)

    provider, client_factory = _artlist_with_mock(tmp_path, handler)
    monkeypatch.setattr(httpx, "Client", client_factory)

    results = provider.search("thunder", SearchFilters(max_results=5))
    assert len(results) == 1
    assert results[0].asset_id == "song-1"
    assert results[0].title == "Distant Thunder"

    path = provider.download(results[0])
    assert path.exists()
    assert path.read_bytes() == b"AUDIODATA"

    # Second download is served from cache (no error even if network changed).
    assert provider.download(results[0]) == path


def test_artlist_token_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTLIST_CLIENT_ID", "id123")
    monkeypatch.setenv("ARTLIST_CLIENT_SECRET", "secret456")
    calls = {"token": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/token" in url:
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if "/search/v1/song" in url:
            return httpx.Response(200, json={"songs": []})
        return httpx.Response(404)

    provider, client_factory = _artlist_with_mock(tmp_path, handler)
    monkeypatch.setattr(httpx, "Client", client_factory)

    provider.search("a", SearchFilters())
    provider.search("b", SearchFilters())
    assert calls["token"] == 1  # token reused across searches
