# How CineSFX chooses sounds (in plain English)

This page explains, for the everyday user, **where your sounds come from** and
**how the plugin decides which sound effects to place on each clip** — and why.

## The short version

For every clip you select, CineSFX:

1. **Looks at the shots** in the clip (it splits the clip into scenes/shots).
2. **Understands each shot** with your chosen AI brain, from one small still frame.
3. **Plans the sound effects** that belong there — the specific things you can see,
   plus a background "room tone" for the location.
4. **Finds a real file** for each planned sound from your chosen source.
5. **Places it on the timeline** at the exact moment, on its own audio track(s),
   in sync — quieter for backgrounds, panned left/right to match the screen.

The loudness, left/right position, and fade in/out are **applied automatically** to
each sound (baked into the audio when it's placed, so it sounds right in your final
export — no manual mixing required). Previewing the plan is always **free**;
actually placing the sounds is the paid action (one-time license).

## Why it picks the combination it does

CineSFX thinks like a sound designer. For each shot it proposes a small, tasteful
mix (by default at most a few cues per scene) built from these ingredients:

- **Spot effects** — the specific, on-screen things you should *hear because you
  see them*: footsteps, a door, cloth movement, an impact, water, a mechanism.
  These are timed to the moment they happen in the shot.
- **One ambience bed per location** — a continuous background (room tone, forest,
  city, wind) that sits **low** in the mix and lasts the whole scene, so the space
  feels alive without drawing attention.
- **Transitions** — the occasional whoosh/riser on a hard cut, when it helps.

Each planned sound also gets:

- **Timing** — placed at the right instant *inside* that shot (never drifting into
  the next one).
- **Pan (left/right)** — matched to where the source appears on screen.
- **Distance** — closer things are louder; far things are gently attenuated.
- **Loudness** — a sensible level, with ambiences kept well below spot effects and
  everything held under a safety ceiling so nothing clips.

The result is a believable layer where you *hear what you see*, in sync — not a
random pile of effects. You always see the full plan in **Preview** first, and the
run report lists anything it intentionally skipped (e.g. a sound it couldn't find,
or an overlap it dropped to avoid clutter).

## Your sound sources ("destinations") explained

Pick one in the panel's **Connections** section. Plain-language guide:

| Source | What it is | Best for | Needs |
|--------|-----------|----------|-------|
| **Freesound** | Big free, community library (public API) | Trying it at zero cost | A free API key |
| **Epidemic Sound** | Pro SFX library (partner API) | Licensed, high-quality SFX | An Epidemic partnership key |
| **Artlist** | Artlist Enterprise API | Existing Artlist Enterprise users | OAuth client id/secret (music today; SFX when Artlist enables it) |
| **Audiio / Musicbed** | No public API | Only if you have bespoke partner access | A partner base URL + token |
| **Splice** | The samples you've synced with the Splice app | Reusing your Splice sounds | Your local Splice folder (auto-detected) |
| **Soundly** | Your local Soundly library folder | Reusing your Soundly SFX | The Soundly library folder |
| **Local folder** | Any single folder of audio you own | A quick, specific folder | The folder path |
| **My sound library (catalog)** | **Many** folders/drives, indexed once | A large personal SFX collection | Your folders (see below) |

Key differences to know:

- **Cloud sources** (Freesound, Epidemic, Artlist) *search the internet* and
  download the chosen file. Great catalogue coverage.
- **Local sources** (Splice, Soundly, Local folder, Catalog) use **files already on
  your computer** — nothing is uploaded and nothing is downloaded; your own files
  are placed directly onto the timeline.
- **Matching** for local sources is based on your file and folder **names**, so
  well-named, well-organised folders give the best results. The **Catalog** source
  is the smartest local option (it also groups sounds into categories).

## Using your own sound files — as many folders as you want

Choose **"My sound library (catalog)"** as your sound source. Then:

1. Click **+ Add folder…** to pick a folder — repeat it to add **as many folders /
   drives as you like** (or type them comma-separated). Example:
   `~/SFX, /Volumes/Drive2/Foley, ~/Music/Sound Effects`
2. Click **Connect**, then **Sync library** to index every sound across all those
   folders into a fast, local index (one plain file — no database, nothing uploaded).
3. Now CineSFX places *your* sounds automatically, fully offline.

### Keeping it in sync when your files change

Your library isn't frozen. When you add, rename, move, or delete sounds:

- Click **Check for changes** — a quick, read-only scan of **all** your folders
  that tells you what would change (e.g. `+40 new, ~3 updated, -5 removed`) without
  touching anything.
- Click **Sync library** — applies it: new files are added, changed files are
  refreshed, and deleted files are pruned, **across every folder you configured**.

Re-syncing is incremental, so it stays fast even for very large libraries. (CLI
equivalents: `python -m scripts.run_cli --check-library` and `--scan-library`; see
[LIBRARY.md](LIBRARY.md).)

## Efficiency & keeping AI cost low

CineSFX is built to be light on the AI:

- Only **tiny, downscaled still frames** are sent to the brain — never your video.
- By default just **one representative frame per shot** is sent, at **low detail**
  (a small, fixed token cost), with a **hard cap on images per request**.
- Scenes are analysed in **batches** and **cached**, so re-running a clip is nearly
  free.
- Long videos stay bounded: too many shots are merged into evenly-spaced scenes so
  an hour-long timeline still costs a predictable amount.

You can tune these in `config.yaml` under `analysis` (`brain_frames_per_scene`,
`max_images_per_request`, `image_detail`) if you ever want more detail at higher
cost. Local/Catalog/Soundly/Splice sources add **no per-sound download or upload**
cost at all.
