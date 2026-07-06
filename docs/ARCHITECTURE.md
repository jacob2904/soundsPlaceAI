# Architecture — soundsPlaceAI / CineSFX

The plugin is built as a **pipeline of cooperating agents**. Each agent has one
responsibility, a small typed interface, and can be developed, tested, and swapped
independently. The `Orchestrator` wires them together and runs work concurrently.

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
- **Writes:** appends downloaded SFX to a dedicated, named audio track using
  `MediaPool.AppendToTimeline([{clipInfo}])` with `mediaType=2` (audio only), `trackIndex`,
  and `recordFrame` for sample-accurate placement. It then sets per-item gain/pan/fades.
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
- Providers: `EpidemicSoundProvider` (full Partner Content API), `ArtlistProvider`,
  `AudiioProvider`, `MusicbedProvider`, `SoundlyProvider` (indexes a **local Soundly library
  folder**), `FreesoundProvider` (free fallback), and `LocalFolderProvider`.
- A `SoundCache` stores downloads under a content-addressed cache dir.

> **Note on platform APIs.** Epidemic Sound and Freesound expose documented public/partner
> REST APIs and are implemented against them. Artlist, Audiio, and Musicbed do not publish
> open developer APIs; their providers implement the same interface against a configurable
> REST base URL (for partners who have credentials) and otherwise raise an actionable error.
> Soundly has no public API, so `SoundlyProvider` works against its **local library folder**
> (the fastest, most reliable integration) and this is also where Soundly's own effects live.

### 5. PlacementAgent — `cinesfx/placement/`
Turns cues + audio files into concrete, synced timeline edits.

- Converts each cue's clip-relative onset (seconds) into an absolute **timeline record frame**
  using the timeline frame-rate.
- Chooses/creates the SFX track(s), avoiding overlap by lane-packing when needed.
- Applies **realistic spatial placement** (`spatial.py`): the brain's `distance` + `pan`
  become gain attenuation, stereo pan, and a subtle low-pass/att for far sounds — the same
  idea Soundly-style tools use to seat a sound in space.
- Adds short fades for clean transitions.

## Orchestrator — `cinesfx/orchestrator.py`
- Loads config + secrets.
- For each selected clip, runs SceneAgent → BrainAgent → SoundAgent concurrently across
  clips (thread pool; the network + ffmpeg work is I/O bound).
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
