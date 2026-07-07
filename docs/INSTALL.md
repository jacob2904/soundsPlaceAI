# Installation & setup

CineSFX needs **DaVinci Resolve 21 Studio** (the free edition does not allow
scripting / Workflow Integrations).

## Easiest: the one-click installer (recommended)

Most people should just use the installer for their OS — it's self-contained, so
there's **nothing else to install** (no Python packages, no FFmpeg, no
`CINESFX_HOME`). After it finishes, the panel works out of the box.

1. **macOS:** open `CineSFX-Installer.dmg` and double-click **Install CineSFX.command**
   (approve the admin prompt).
   **Windows:** run `CineSFX-Setup.exe`.
2. Restart DaVinci Resolve.
3. Open **Workspace ▸ Workflow Integrations ▸ CineSFX AI**.
4. In the panel's **Connections** section, pick your AI brain + audio source and
   click **Connect** (see [CONNECTIONS.md](CONNECTIONS.md)). That's it.

> The installer copies a bundled plugin into Resolve's *Workflow Integration
> Plugins* folder; `plugin/cinesfx_bootstrap.py` wires the bundled dependencies +
> FFmpeg at launch. To remove it, delete the `com.soundsplaceai.cinesfx` folder
> (paths in the table below) or run `python -m cinesfx.installer --uninstall`.

**Building the installers** (maintainers, on each OS): see
[`packaging/README.md`](../packaging/README.md). In short:
`bash packaging/macos/build_dmg.sh` (macOS) or
`powershell -File packaging\windows\build_exe.ps1` (Windows).

**Install from a checkout without an installer:** `python -m cinesfx.installer`
copies the plugin into the right Resolve folder for your OS.

---

## Manual / developer setup

The rest of this page covers running from source (for development or the CLI). It
additionally needs Python 3.9+ and FFmpeg on your `PATH`.

## 1. Get the code and dependencies

```bash
git clone <this-repo> soundsPlaceAI
cd soundsPlaceAI
python -m pip install -r requirements.txt
# then install ONLY the brain SDK you want to use, e.g.:
python -m pip install google-generativeai      # Gemini
# python -m pip install openai                  # OpenAI
# python -m pip install anthropic               # Claude
```

Install FFmpeg:
- macOS: `brew install ffmpeg`
- Windows: `winget install Gyan.FFmpeg` (or download a static build)
- Linux: `sudo apt install ffmpeg`

## 2. Configure

```bash
cp .env.example .env          # add your API keys here (never commit this)
cp config.example.yaml config.yaml
```

Edit `config.yaml` to choose your `brain` (gemini/openai/claude) and
`sound_provider` (epidemic/freesound/artlist/audiio/musicbed/splice/soundly/local/
catalog), and set any local library paths.

> **Fastest zero-cost setup:** `brain: gemini` + `sound_provider: freesound`. Both
> only need a free API key.

## 3a. Run from the command line

With a project + timeline open in Resolve:

```bash
python -m scripts.run_cli --selection --dry-run   # preview the plan
python -m scripts.run_cli --selection             # place SFX on current clip
python -m scripts.run_cli --all                   # whole timeline
python -m scripts.run_cli --color Orange          # only clips you coloured Orange
```

For the CLI to reach Resolve, enable **Resolve ▸ Preferences ▸ System ▸ General ▸
"External scripting using"** (set to Local), and make sure the scripting
environment variables are set (Resolve sets these on install; if not, see the
"Scripting connection" section below).

## 3b. Install the Workflow Integration panel

Copy the plugin into Resolve's Workflow Integration Plugins folder, inside a folder
named `com.soundsplaceai.cinesfx`:

| OS      | Workflow Integration Plugins folder |
|---------|--------------------------------------|
| macOS   | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/` |
| Windows | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\` |
| Linux   | `/opt/resolve/Workflow Integration Plugins/` |

```bash
# example (macOS); create the com.soundsplaceai.cinesfx folder there and copy files
DEST="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/com.soundsplaceai.cinesfx"
mkdir -p "$DEST"
cp plugin/CineSFX.py plugin/manifest.xml "$DEST"/
# Tell the plugin where this repo lives so it can import the cinesfx package:
export CINESFX_HOME="$(pwd)"
```

Then launch Resolve and open **Workspace ▸ Workflow Integrations ▸ CineSFX AI**.

> Prefer the Scripts menu? Copy `plugin/CineSFX.py` into the Resolve
> `Scripts/Utility` folder instead and run it from **Workspace ▸ Scripts**.

Set `CINESFX_HOME` (an environment variable pointing at this repository root) so
the panel can import the `cinesfx` package. Alternatively `pip install -e .` into
the Python that Resolve uses.

## Scripting connection (if the CLI can't find Resolve)

Set these (paths shown for macOS; adjust for your OS — see the table above):

```bash
export RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
export RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
export PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"
```

## How you "choose which clips"

Because Resolve's scripting API does not expose arbitrary multi-selection of
timeline items, CineSFX offers three reliable ways to pick clips:

1. **Current clip** — the item under the playhead.
2. **Whole timeline** — every clip (great for finishing a full cut).
3. **Colored clips** — tag the clips you want with a clip color (right-click ▸ Clip
   Color) and choose that color. This is the recommended way to hand-pick many
   specific shots.
