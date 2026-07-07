# Architecture — soundsPlaceAI / CineSFX

The plugin is built as a **pipeline of cooperating agents**. Each agent has one
responsibility, a small typed interface, and can be developed, tested, and swapped
independently. The `Orchestrator` wires them together and runs work concurrently.

> New to the codebase? Pair this with [`DEVELOPING.md`](DEVELOPING.md) (setup +
> how to extend) and skim [`cinesfx/models.py`](../cinesfx/models.py) first — those
> dataclasses are the shared vocabulary every agent speaks.

```
                    ┌──────────────────────────────────────────────────────────┐
                    │                     Orchestrator                          │
                    │  (config, concurrency, caching, dry-run, cost estimate)   │
                    └───────┬───────────┬───────────┬───────────┬──────────────┘
                            │           │           │           │
            ┌───────────────▼──┐  ┌─────▼──────┐  ┌─▼──────────┐  ┌▼───────────────┐
            │  TimelineAgent   │  │ SceneAgent │  │ BrainAgent │  │  SoundAgent    │
            │ (Resolve I/O)    │  │ (analysis) │  │  (LLM)     │  │ (SFX platforms)│
            └───────┬──────────┘  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘
                    │                   │               │                 │
                    │            keyframes+times   scene→SFX cues    downloaded audio
                    │                   │               │                 │
                    │                   └──────────────►│◄────────────────┘
                    │                                   │
                    │                          ┌────────▼─────────┐
                    └─────────────────────────►│  PlacementAgent  │
                     insert audio on SFX track │ (timing/gain/pan)│
                                               └──────────────────┘
```

## The agents

### 1. TimelineAgent — `cinesfx/resolve/`
The only module that talks to DaVinci Resolve.

- **Input:** the running Resolve app (via the standard `DaVinciResolveScript` fusionscript
  module) and the user's current selection or the whole current timeline.
- **Reads:** for each selected `TimelineItem` — its source media **file path**
  (`GetMediaPoolItem().GetClipProperty("File Path")`), the clip's source in/out frames
  (`GetLeftOffset`/`GetRightOffset`/`GetSourceStartFrame`), its timeline position
  (`GetStart`/`GetEnd`), and the timeline frame-rate.
- **Writes:** appends the (already-processed) SFX to a dedicated, named audio track using
  `MediaPool.AppendToTimeline([{clipInfo}])` with `mediaType=2` (audio only), `trackIndex`,
  and `recordFrame` for sample-accurate placement.
- **Gain/pan/fades are baked in first.** Resolve's scripting API doesn't expose per-clip
  audio gain/pan/fades, so the `AudioRenderer` (`cinesfx/audio/render.py`) pre-renders each
  SFX with FFmpeg — `volume` (gain incl. distance attenuation), a constant-power stereo
  `pan`, `afade` in/out, trimmed to the exact placed length — so the clip sounds correct in
  the final render. A marker + clip name record the applied values (and if FFmpeg is missing
  it falls back to the raw file, keeping just the annotation).
- Never touches the user's original clips → non-destructive.

Because we work from the *source file* and Resolve's frame math, **no export/upload of the
video is ever required**.

### 2. SceneAgent — `cinesfx/analysis/`
Turns a video file + frame range into a compact, LLM-ready description.

- Runs **PySceneDetect** (`ContentDetector`/`AdaptiveDetector`) on only the requested range,
  with `downscale_factor` for speed, to find shot boundaries.
- For each shot, extracts a few **downscaled key-frames** with `ffmpeg -ss <t> -i ... -vf
  scale=...` (seek-before-input = cheap seeking on long files).
- Emits `Scene` objects (start/end seconds relative to the clip, key-frame image paths).
- Everything is cached by `(file content hash, range, params)` so re-runs are free.

### 3. BrainAgent — `cinesfx/brain/`
The pluggable "understanding" layer. Providers implement `BrainProvider`:

- `describe_and_plan(scenes, context) -> list[SfxCue]`
- Sends the small key-frames + timing context and a strict JSON schema prompt.
- Returns **structured cues**: description, search query, category, onset (s, relative to
  clip), duration, gain (dB), pan (-1..1), distance (0..1 = close..far), diegetic flag,
  and confidence.
- Providers: `GeminiBrain`, `OpenAIBrain`, `ClaudeBrain`. Selected by config/env; the factory
  validates that the matching SDK + key are present and raises a clear error otherwise.

### 4. SoundAgent — `cinesfx/sound/`
The pluggable licensing/library layer. Providers implement `SoundProvider`:

- `search(query, filters) -> list[SoundAsset]`
- `download(asset) -> Path` (cached by asset id + content hash)
- Providers (one file each, chosen by `sound_provider` + built in `factory.py`):
  `EpidemicSoundProvider` (full Partner Content API), `FreesoundProvider` (free public
  API), `ArtlistProvider` (Enterprise OAuth2, music today), `SpliceProvider` and
  `SoundlyProvider` (index a **local library folder**), `LocalFolderProvider` (any folder),
  `CatalogProvider` (the user's own cataloged library — see below), and a generic
  `PartnerRestProvider` for Audiio/Musicbed.
- A `SoundCache` (`cache.py`) stores downloads under a content-addressed cache dir.

> **Note on platform APIs.** Which platforms actually expose a usable API is documented,
> with sources, in [`PROVIDERS.md`](PROVIDERS.md). In short: Epidemic Sound and Freesound
> have real REST APIs; Artlist has an Enterprise API (music only for now); Splice and
> Soundly have no public API so they're integrated via their **local folders**; Audiio and
> Musicbed have no public API and fall back to a configurable partner-REST provider.

### 4b. Library catalog — `cinesfx/library/`
Backs the `CatalogProvider` so users can place from **their own sounds on disk**.

- `LibraryCatalog` scans one or many root folders and records each audio file (name,
  folder, ext, size, mtime, inferred category, searchable tokens, optional duration) in a
  single **JSON file — no database**.
- Re-scanning is **incremental** (skip unchanged, refresh changed, prune deleted) and
  supports a **`dry_run`** mode to *detect* changes without writing — this is what powers
  the panel's "Check for changes" / "Sync library" resync buttons.
- Search ranks by name/folder token overlap, loaded into memory once and cached so the many
  per-cue lookups a run performs stay fast. See [`LIBRARY.md`](LIBRARY.md).

### 5. PlacementAgent — `cinesfx/placement/`
Turns cues + audio files into concrete, synced timeline edits.

- Converts each cue's clip-relative onset (seconds) into an absolute **timeline record frame**
  using the timeline frame-rate.
- Chooses/creates the SFX track(s), avoiding overlap by lane-packing when needed.
- Applies **realistic spatial placement** (`spatial.py`): the brain's `distance` + `pan`
  become gain attenuation, stereo pan, and a subtle low-pass/att for far sounds — the same
  idea Soundly-style tools use to seat a sound in space.
- Adds short fades for clean transitions.

## Audio renderer — `cinesfx/audio/render.py`
- Bakes each placement's gain/pan/fades into the SFX file with FFmpeg (trimmed to the placed
  length), so the values are actually audible in the render. Content-addressed + cached, and
  a no-op fallback when FFmpeg is absent.

## Orchestrator — `cinesfx/orchestrator.py`
- Loads config + secrets.
- For each selected clip, runs SceneAgent → BrainAgent → SoundAgent concurrently across
  clips (thread pool; the network + ffmpeg work is I/O bound), then bakes the audio fx
  (non-preview runs) so placement is parallel too.
- Collects a `PlacementPlan`, prints a human-readable preview + cost estimate, and — unless
  `--dry-run` — hands it to the PlacementAgent.

## Data model — `cinesfx/models.py`
`ClipSelection`, `Keyframe`, `Scene`, `SfxCue`, `SoundAsset`, `PlannedPlacement`,
`PlacementPlan` — all typed dataclasses that flow between agents.

## Concurrency choice
Resolve's scripting bridge is synchronous and not thread-safe for writes, so:
- **Read + analyse + brain + download** happen concurrently across clips in a `ThreadPool`.
- **All timeline writes** are marshalled back to a single thread in the PlacementAgent.

This keeps the fast, parallel, network/CPU work off the Resolve main thread while guaranteeing
safe, ordered edits.

## Supporting modules

These are not agents but everything depends on them:

- **`config.py`** — loads/validates `config.yaml`, deep-merges the persisted user settings
  overlay, and reads secrets from the environment (never from the logged config object).
- **`settings.py`** + **`user_store.py`** — persist the end-user's changeable UI choices
  (brain, provider, scope, provider folders, license) in the per-user, cross-platform config
  directory as JSON.
- **`licensing.py`** — offline Ed25519 signature verification for the one-time lifetime
  license; `tools/` holds the vendor-side keypair/license generators. See
  [`LICENSING.md`](LICENSING.md).
- **`diagnostics.py`** — the "Test connection" self-checks (Resolve, ffmpeg, brain key,
  sound provider, license) surfaced in the panel and via `run_cli --doctor`.
- **`logging_utils.py`** — logging configured to redact secrets from every line.

## Entry points

- **`plugin/CineSFX.py`** — the Resolve panel. It is deliberately thin: it reads/saves
  settings and calls the `Orchestrator` (and the catalog for library sync).
- **`scripts/run_cli.py`** — the command-line runner (also installed as the `cinesfx`
  console script) for previews, real runs, licensing, diagnostics, and library scan/resync.

## Repository layout

See the "Repository layout" tree in the top-level [`README.md`](../README.md) for a
one-line description of every directory, and [`DEVELOPING.md`](DEVELOPING.md) for how to
set up and extend the project.
