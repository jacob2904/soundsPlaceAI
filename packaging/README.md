# Building the one-click installers (.dmg / .exe)

These produce a **self-contained** CineSFX plugin that a user installs by
double-clicking, after which the panel works out of the box in DaVinci Resolve —
no `pip install`, no `CINESFX_HOME`, no manual file copying.

## What "self-contained" means

The installers ship a `payload/` folder that already contains everything:

```
payload/
  CineSFX.py, cinesfx_bootstrap.py, manifest.xml   # the panel
  cinesfx/            # the engine package
  scripts/            # optional CLI
  config.example.yaml
  libs/               # vendored Python dependencies (pip --target)
  ffmpeg/             # (optional) bundled FFmpeg binaries
```

At runtime `cinesfx_bootstrap.py` adds `libs/` to `sys.path` and `ffmpeg/` to
`PATH`, so the plugin runs regardless of what's on the user's machine. The user
then just connects their AI key / audio source in the panel's **Connections** tab.

> Note: the plugin runs inside **DaVinci Resolve 21 Studio**'s Python, so the
> vendored `libs/` must be built with a compatible Python (3.9–3.11). Build on the
> same OS you're targeting so binary wheels (e.g. PySceneDetect/OpenCV) match.

## macOS → `.dmg`

Run on macOS (needs `python3` and `hdiutil`):

```bash
bash packaging/macos/build_dmg.sh
# → build/CineSFX-Installer.dmg
```

The DMG contains `payload/` and **Install CineSFX.command**. The user opens the
DMG and double-clicks the command; it copies the plugin into
`/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins/`
(prompting for admin) and tells them to restart Resolve.

**FFmpeg (optional but recommended):** before packing, drop a static macOS
`ffmpeg`/`ffprobe` into `build/dmgroot/payload/ffmpeg/` (or re-run and add them),
so audio fx work without a separate FFmpeg install.

**Distribution:** code-sign and notarize so Gatekeeper doesn't block it:

```bash
codesign --deep --force --options runtime --sign "Developer ID Application: …" \
  "build/dmgroot/Install CineSFX.command"
xcrun notarytool submit build/CineSFX-Installer.dmg --keychain-profile "AC" --wait
xcrun stapler staple build/CineSFX-Installer.dmg
```

## Windows → `.exe`

Run on Windows in PowerShell (needs Python and [Inno Setup](https://jrsoftware.org/isdl.php)):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build_exe.ps1
# → build\CineSFX-Setup.exe
```

`CineSFX-Setup.exe` installs straight into
`%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\com.soundsplaceai.cinesfx`
and includes an uninstaller. No Python needed on the user's machine (deps are in
`libs/`).

**FFmpeg (optional):** drop `ffmpeg.exe`/`ffprobe.exe` into `build\payload\ffmpeg\`
before compiling.

**Distribution:** sign the installer:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 build\CineSFX-Setup.exe
```

## Staging only (CI / manual)

`stage_payload.py` assembles the payload (and vendors deps) without packing:

```bash
python packaging/stage_payload.py --out build/payload            # payload + deps
python packaging/stage_payload.py --out build/payload --no-deps  # code only
```

## Install without an installer (advanced)

Any Python can install a checkout directly (used for dev/testing):

```bash
python -m cinesfx.installer            # copy the plugin into Resolve's folder
python -m cinesfx.installer --uninstall
```
