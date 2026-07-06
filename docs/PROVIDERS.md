# Sound providers — what's actually possible

I checked each platform's developer documentation. Here is the honest, current
state of what CineSFX can do with each, and how each one is wired in. Everything
that returns an audio file plugs into the **same** Resolve placement layer, so all
working providers integrate seamlessly with the timeline.

## Capability matrix

| Provider | Official API? | Search | Download | SFX today? | How CineSFX integrates |
|---|---|---|---|---|---|
| **Epidemic Sound** | ✅ Partner Content API | ✅ | ✅ | ✅ **Yes** | Cloud API (key). Full SFX search + MP3 download. |
| **Freesound** | ✅ Public API (free) | ✅ | ✅ | ✅ **Yes** | Cloud API (free key). CC-licensed SFX. |
| **Soundly** | ❌ none | ✅ | ✅ | ✅ **Yes** | **Local library folder** (index + match). |
| **Splice** | ❌ none (only unofficial gRPC) | ✅ | ✅ | ✅ **Yes** (samples/one-shots) | **Local Splice folder** (auto-detected). |
| **Local folder** | n/a | ✅ | ✅ | ✅ **Yes** | Any folder of audio files you own. |
| **Catalog (your library)** | n/a | ✅ | ✅ | ✅ **Yes** | Index your **whole computer's** sounds once; place from a fast persistent catalog. See [LIBRARY.md](LIBRARY.md). |
| **Artlist** | ✅ Enterprise API (OAuth2) | ✅ | ✅ | ⚠ **Music only** | Cloud API (client id/secret). SFX not yet exposed by Artlist. |
| **Audiio** | ❌ none (enterprise/bespoke) | — | — | ✗ | Configurable partner-REST fallback only. |
| **Musicbed** | ❌ none (enterprise/bespoke) | — | — | ✗ | Configurable partner-REST fallback only. |

**For cinematic sound effects today, use:** Epidemic Sound, Freesound, Soundly
(local), Splice (local), a local folder, or your own **catalog** (index every
sound on your computer — see [LIBRARY.md](LIBRARY.md)). These all work end-to-end.

## Details & sources

### Epidemic Sound — ✅ works for SFX
Documented **Partner Content API** with dedicated sound-effect search
(`/v0/sound-effects/search`) and download (`/v0/sound-effects/{id}/download`).
Requires a partnership + API key (bearer). Implemented in
`cinesfx/sound/epidemic.py`.

### Freesound — ✅ works for SFX (free)
Open API with a free key. Great zero-cost default. High-quality MP3 previews are
downloadable with just the token. Implemented in `cinesfx/sound/freesound.py`.
(Results are Creative Commons; attribution varies per sound.)

### Soundly — ✅ works for SFX (local)
Soundly has **no public cloud API**. The reliable, seamless integration is to read
your **local Soundly library folder** — the same effects you already use in
Soundly. Implemented in `cinesfx/sound/soundly.py`.

### Splice — ✅ works (local), no official API
Splice does **not** offer an official developer API. The only programmatic access
is unofficial, reverse-engineered gRPC that violates Splice's terms and breaks
frequently — so CineSFX does **not** use it. Instead it reads your **local Splice
folder** (the samples the Splice desktop app has synced), exactly like DAWs
integrate Splice. Auto-detected at `~/Splice` or `~/Documents/Splice`, or set
`sound_providers.splice.library_path`. Implemented in `cinesfx/sound/splice.py`.
Note: Splice's catalogue is production samples/one-shots/FX rather than a dedicated
cinematic SFX library, but its one-shots and FX are useful for design.

### Catalog (your own library) — ✅ works for SFX, offline
Point CineSFX at one or more folders on your computer and it indexes **every**
audio file into a small, persistent **JSON catalog file** — no database (name,
folder, category, searchable tokens, optional duration). Re-scanning is incremental (only changed
files are touched, deleted files are pruned), so keeping a huge library current is
cheap. Placement then searches that catalog and drops your own files onto the
timeline — no uploads, no downloads, fully offline. Set
`sound_providers.catalog.roots`, scan with the panel's **Scan library** button (or
`--scan-library`), and pick `catalog` as the provider. Implemented in
`cinesfx/library/catalog.py` + `cinesfx/sound/catalog.py`. Full guide:
[LIBRARY.md](LIBRARY.md).

### Artlist — ⚠ real API, music only (for now)
Artlist publishes a real **Enterprise API** (`developer.artlist.io`) using OAuth 2.0
Client Credentials. It has search (`/search/v1/song`) and download
(`/download/v1/downloadable/{assetType}/{id}/{format}`). **However**, the API's
supported `assetType` is currently `song` (music) — Artlist's SFX are not yet
exposed via the API. CineSFX implements the real endpoints and exposes an
`asset_type` setting (default `song`) so SFX will work the instant Artlist enables
that type, with no code change. Credentials are issued by an Artlist account
manager (`ARTLIST_CLIENT_ID` / `ARTLIST_CLIENT_SECRET`). Implemented in
`cinesfx/sound/artlist.py`.

### Audiio — ✗ no public API
Audiio (the licensing platform) has no public developer API for third-party SFX
integration. (An unrelated open-source music-player project also called "audiio"
exists on GitHub; that is not this service.) CineSFX keeps a configurable
partner-REST provider for anyone with a bespoke Audiio integration, otherwise it
raises a clear error pointing you to a supported provider.

### Musicbed — ✗ no public API
Musicbed operates through enterprise/bespoke licensing and account management, not
a self-service developer API. Same configurable partner-REST fallback as Audiio.

## Adding another provider

Every provider implements one tiny interface (`cinesfx/sound/base.py`):

```python
class SoundProvider:
    def search(self, query, filters) -> list[SoundAsset]: ...
    def download(self, asset) -> Path: ...
```

So adding, say, **Pro Sound Effects** (which does offer a Partner API with
search/preview/download) is ~40 lines: implement those two methods and register the
name in `cinesfx/sound/factory.py`. Because the placement/timeline layer only cares
about the returned file, any new provider is automatically "seamless with Resolve".
