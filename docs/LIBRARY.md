# Use your own sound library

CineSFX can place sounds from **your own computer** — no cloud account required.
Point it at the folders where you keep audio, let it **catalog** everything once,
and the AI will drop your own files onto the Resolve timeline in sync with the
picture.

This is the `catalog` sound provider. It is fully offline: nothing is uploaded and
nothing is downloaded — your files are already on disk.

## How it works

1. **Scan** — CineSFX walks the folders you choose and records each audio file in a
   small [SQLite](https://sqlite.org) catalog: file name, folder, extension, size,
   modified-time, an inferred category (footsteps, door, water, impact, …), and a
   set of searchable tokens taken from the file and folder names. Durations are
   optional (see below).
2. **Match** — When the brain asks for, say, *"wooden door creaks open"*, CineSFX
   searches the catalog by token overlap on those names and returns your best files.
3. **Place** — The chosen file is inserted on the CineSFX audio track at the right
   frame, with the same spatialisation (gain/pan/fades) as any other provider.

Re-scanning is **incremental**: unchanged files are skipped, changed files are
refreshed, and files you deleted on disk are removed from the catalog — so keeping a
large library up to date is fast.

Supported audio types: `.wav .mp3 .aif .aiff .flac .ogg .m4a`.

## 1. Choose your folders

**In the panel:** pick **Sound library → catalog**, then type one or more folders in
the *Library folder(s)* field, comma-separated:

```
~/SFX, ~/Music/Sound Effects, /Volumes/Audio/Libraries
```

**Or in `config.yaml`:**

```yaml
sound_provider: catalog

sound_providers:
  catalog:
    roots:
      - ~/SFX
      - ~/Music/Sound Effects
    # db_path: ~/.cache/cinesfx/library.db   # optional; defaults inside cache_dir
    probe_duration: false                    # true = read durations (needs 'tinytag')
    auto_scan: false                         # true = auto-index on first use if empty
```

## 2. Scan (catalog) your sounds

**In the panel:** click **Scan library**. Progress appears in the output box and the
catalog is saved for next time.

**From the command line:**

```bash
# Scan the folders from config.yaml
python -m scripts.run_cli --scan-library

# Or scan specific folders (overrides config)
python -m scripts.run_cli --scan-library --library-roots "~/SFX" "~/Music/Sound Effects"

# Also read durations while scanning (needs the optional 'tinytag' package)
python -m scripts.run_cli --scan-library --probe-duration

# See what's in your catalog
python -m scripts.run_cli --library-stats
```

Example output:

```
1234 sound(s) in catalog (+1234 new, ~0 updated, -0 removed, 0 unchanged) in 3.8s
```

## 3. Place from your library

Set the sound provider to **catalog** (panel dropdown or `sound_provider: catalog`),
then **Preview** (free) or **Place SFX** exactly as with any other provider. Your own
sounds are matched to each scene and placed in sync.

## Tips for great matches

Matching is only as good as your file/folder names. Descriptive names help a lot:

- Good: `Doors/Wooden/door_creak_open_slow.wav`, `Footsteps/Gravel/run_gravel_01.wav`
- Weak: `sfx_004.wav`, `render final v2.wav`

Folder names count too (up to a few levels), so a well-organised library
(`.../Water/Ocean/...`) matches naturally.

## Optional: durations

CineSFX doesn't need durations — the true length is read from Resolve once a clip is
imported. But if you want durations in the catalog (for reporting or ambience-bed
defaults), install the optional, pure-Python reader and scan with `--probe-duration`:

```bash
pip install tinytag
python -m scripts.run_cli --scan-library --probe-duration
```

## Where the catalog lives

A single file, by default `~/.cache/cinesfx/library.db` (override with
`sound_providers.catalog.db_path`). It's safe to delete at any time — just re-scan.
The catalog stores only file **paths and metadata**, never the audio itself, and it
never leaves your machine.

## Troubleshooting

- **"Your sound catalog is empty."** — Run a scan first (panel **Scan library** or
  `--scan-library`).
- **"No library folders configured."** — Add at least one folder to
  `sound_providers.catalog.roots` (or the panel field).
- **A file was placed that no longer exists** — You moved/deleted it after scanning;
  re-scan to refresh the catalog.
- **Check status any time:** `python -m scripts.run_cli --doctor` reports how many
  sounds are indexed.
