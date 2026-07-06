# soundsPlaceAI — CineSFX for DaVinci Resolve 21 Studio

**AI-driven cinematic sound-effects placement for the DaVinci Resolve 21 Studio timeline.**

`soundsPlaceAI` watches the clips you select on your Resolve timeline, *understands each
scene* using a vision-capable LLM ("the brain"), finds matching sound effects from the
licensing platform of your choice (Epidemic Sound, Artlist, Audiio, Musicbed, a local
Soundly library, Freesound, or a plain folder), and drops them onto dedicated SFX tracks in
**perfect sync** with what is happening on screen.

It does **not** generate audio. It *places* real, licensed sound effects so every scene
sounds cinematic — footsteps, doors, whooshes, ambiences, impacts, room tone — each one
timed to the moment it is seen.

---

## Why it is fast and efficient

The plugin **never uploads your whole video** anywhere:

1. It reads the *source media file path* of each selected timeline clip directly from
   Resolve (no re-encode, no export).
2. It runs **local, content-aware shot detection** (PySceneDetect) on only the in/out range
   of each selected clip.
3. It extracts a handful of **small, downscaled key-frames** per shot with `ffmpeg`
   (seek-before-decode, so it is cheap even on multi-hour files).
4. Only those tiny key-frame JPEGs are sent to the LLM brain — not the video.
5. Only the *chosen* sound-effect files are downloaded, and everything is cached by content
   hash so repeat runs are instant.
6. Selected clips are analysed **in parallel** with a worker pool.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design and the agent
breakdown.

---

## Feature highlights

- **Per-clip or whole-timeline** operation — sweeten one shot or sound-design a finished cut.
- **Scales to long videos** — smart, whole-video key-frame sampling + batched AI calls keep
  hour-long clips fast and affordable. See [`docs/LONG_VIDEOS.md`](docs/LONG_VIDEOS.md).
- **Pluggable "brain"** — Gemini, OpenAI (GPT-4o/o-series vision), or Claude, chosen at
  runtime by API key.
- **Pluggable sound platforms** — Epidemic Sound (full Partner API), Artlist, Audiio,
  Musicbed, a local **Soundly** library, Freesound (free fallback), or a local folder. Add
  your own by implementing one small interface.
- **Beautiful, easy panel** — a polished dark UI with live progress; your choices are
  **saved and can be changed any time** ([`docs/SETTINGS.md`](docs/SETTINGS.md)).
- **Scene understanding first** — the brain returns structured cues (what to place, when,
  how loud, where in the stereo field) *before* anything touches your timeline.
- **Realistic, Soundly-style placement** — cues carry distance/pan hints that are converted
  into gain + pan + fades so sounds sit believably in the scene.
- **Non-destructive** — SFX land on their own named audio tracks; your original audio is
  never modified.
- **Free Preview + one-time lifetime license** — previewing the full plan is always free;
  placing SFX unlocks with a single perpetual, offline-verified license
  ([`docs/LICENSING.md`](docs/LICENSING.md)).

---

## Quick start

**➡ The fastest, step-by-step path to testing it is [`docs/QUICKSTART.md`](docs/QUICKSTART.md)
(~5 minutes, free tools, no license needed for Preview).**

```bash
# 1. Install (into the Python that DaVinci Resolve uses, or a venv for CLI use)
python -m pip install -r requirements.txt
python -m pip install google-generativeai            # a free-tier brain

# 2. Configure secrets (never commit this file)
cp .env.example .env
#   add GEMINI_API_KEY (free) and FREESOUND_API_KEY (free) to start

# 3. (optional) advanced non-secret defaults
cp config.example.yaml config.yaml

# 4a. Preview against the open Resolve timeline (free, no changes made)
python -m scripts.run_cli --selection --dry-run

# 4b. Activate once (one-time lifetime), then place SFX for real
python -m scripts.run_cli --activate "CINESFX-1.…"
python -m scripts.run_cli --selection

# 4c. Or use the panel: Workspace ▸ Scripts ▸ CineSFX (or Workflow Integrations)
```

Docs:
[`QUICKSTART`](docs/QUICKSTART.md) ·
[`INSTALL`](docs/INSTALL.md) ·
[`ARCHITECTURE`](docs/ARCHITECTURE.md) ·
[`LONG_VIDEOS`](docs/LONG_VIDEOS.md) ·
[`LICENSING`](docs/LICENSING.md) ·
[`SETTINGS`](docs/SETTINGS.md)

---

## Security & privacy

- All credentials are read from environment variables / `.env` — **never** hard-coded. Secret
  values are redacted from every log line.
- Only downscaled key-frames (not your footage) leave the machine, and only when you run the
  brain step. Choose a fully local pipeline (local sound folder + a self-hosted brain) if you
  need zero data egress.
- Only HTTPS endpoints are used for every platform.

## Status

This repository is a complete, runnable reference implementation. The DaVinci Resolve and
paid-platform calls require DaVinci Resolve **Studio** and the relevant API credentials /
partnership agreements to be present at runtime; every module is unit-tested and degrades
gracefully with clear error messages when a dependency or credential is missing.

## License

MIT — see [`LICENSE`](LICENSE).
