# Quick start — install & test CineSFX in ~5 minutes

This is the fastest path to *seeing it work*. It uses the **free** brain/sound
options and the **Preview** mode (which is free and needs no license).

> Requirements: DaVinci Resolve **21 Studio**, Python 3.9+, and FFmpeg.

---

## Step 1 — Install the code

```bash
git clone <this-repo> soundsPlaceAI
cd soundsPlaceAI
python -m pip install -r requirements.txt
python -m pip install google-generativeai          # the (free-tier) Gemini brain
```

Install FFmpeg if you don't have it:
- macOS: `brew install ffmpeg`  ·  Windows: `winget install Gyan.FFmpeg`  ·  Linux: `sudo apt install ffmpeg`

## Step 2 — Add two free API keys

```bash
cp .env.example .env
```

Open `.env` and fill in:
- `GEMINI_API_KEY` — free key from https://aistudio.google.com/apikey
- `FREESOUND_API_KEY` — free key from https://freesound.org/apiv2/apply/

That's all you need to try it. (You can switch to Epidemic Sound / Artlist /
Audiio / Musicbed / a local Soundly library later — see below.)

## Step 3 — Install the panel into Resolve

Pick **one** of these:

**A) Scripts menu (simplest for testing):**
Copy `plugin/CineSFX.py` into Resolve's `Scripts/Utility` folder:

| OS | Scripts/Utility folder |
|----|------------------------|
| macOS | `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/` |
| Windows | `%APPDATA%\Blackmagic Design\DaVinci Resolve\Fusion\Scripts\Utility\` |
| Linux | `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/` |

**B) Workflow Integration (adds it under Workspace ▸ Workflow Integrations):**
see [`INSTALL.md`](INSTALL.md) for the exact folder + `manifest.xml`.

Then tell the panel where this repo lives so it can import the engine:

```bash
export CINESFX_HOME="/full/path/to/soundsPlaceAI"     # add to your shell profile
```
(On Windows set a `CINESFX_HOME` environment variable to the repo path.)

## Step 4 — Try it (free Preview)

1. Open a project + timeline in Resolve. Put the playhead on a clip.
2. Launch the panel:
   - Scripts route: **Workspace ▸ Scripts ▸ CineSFX**
   - Workflow route: **Workspace ▸ Workflow Integrations ▸ CineSFX**
3. Leave **Brain = gemini**, **Sound = freesound**, **Scope = Current clip**, and
   keep **"Preview only"** checked.
4. Click **Preview (free)**. In a few seconds the output panel lists the scenes it
   understood and the exact SFX + timings it *would* place. No changes are made.

Prefer the terminal? With Resolve open:

```bash
python -m scripts.run_cli --selection --dry-run
```

## Step 5 — Actually place the SFX (needs a license)

Placing sound effects onto the timeline is the paid action (one-time, lifetime).
Activate your key once:

- In the panel: click **Enter license**, paste your `CINESFX-1.…` key, **Activate**.
- Or in the terminal: `python -m scripts.run_cli --activate "CINESFX-1.…"`

Then uncheck "Preview only" and click **Place SFX** (or run
`python -m scripts.run_cli --selection`). CineSFX creates a dedicated **CineSFX**
audio track (or several lanes) and drops each effect in sync — your original audio
is never touched.

> **Just testing without a key yet?** You can mint yourself a trial key with the
> included demo signer (see [`LICENSING.md`](LICENSING.md)). Preview mode already
> shows the full result for free.

---

## Choosing (and changing) your setup

Everything you pick in the panel — brain, sound library, scope, folders — is
**saved automatically** and restored next time. Change it whenever you like; the
new choice sticks. (Settings live in a small file under your user config dir; see
[`SETTINGS.md`](SETTINGS.md).)

- **Switch brain:** pick gemini / openai / claude (add that SDK + its key in `.env`).
- **Switch sound library:** pick epidemic / artlist / audiio / musicbed / soundly /
  freesound / local. For **soundly**/**local**, set the *Local library folder* field
  to your sounds directory.

## What about long videos?

CineSFX is built for them — it samples key-frames *smartly across the whole video*
and batches the AI calls so an hour-long clip is fast and affordable. See
[`LONG_VIDEOS.md`](LONG_VIDEOS.md).

## Troubleshooting

- **"Fusion UIManager is unavailable"** — run the panel from *inside* Resolve.
- **"Could not import DaVinciResolveScript"** (CLI) — enable Resolve ▸ Preferences ▸
  System ▸ General ▸ External scripting = Local, and see the scripting env vars in
  [`INSTALL.md`](INSTALL.md).
- **"No clips matched"** — put the playhead on a clip (Current), or choose Whole
  timeline / Colored clips.
- **Missing API key** — the panel/CLI tell you exactly which key to add to `.env`.
