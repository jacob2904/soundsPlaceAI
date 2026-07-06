"""CineSFX — DaVinci Resolve Workflow Integration / Script panel.

A polished, easy-to-use panel that:
  * remembers your choices (brain, sound library, scope) and lets you change them
    any time,
  * offers a free **Preview** and a licensed **Place SFX** action,
  * activates your one-time lifetime license,
  * shows live progress while it works.

Drop this file into the Resolve "Workflow Integration Plugins" folder (inside
``com.soundsplaceai.cinesfx``) or the "Scripts/Utility" folder. See
docs/INSTALL.md for exact paths. Set CINESFX_HOME to this repo so the ``cinesfx``
package can be imported.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback

_REPO_ROOT = os.environ.get(
    "CINESFX_HOME", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from cinesfx.config import ConfigError, load_config  # noqa: E402
from cinesfx.orchestrator import Orchestrator  # noqa: E402
from cinesfx.resolve.timeline_agent import (  # noqa: E402
    SELECT_ALL,
    SELECT_COLOR,
    SELECT_CURRENT,
    TimelineAgent,
)
from cinesfx.settings import (  # noqa: E402
    UserSettings,
    activate_license,
    get_license_status,
)

resolve = globals().get("resolve")
fusion = globals().get("fusion")
bmd = globals().get("bmd")

WINDOW_ID = "com.soundsplaceai.cinesfx"

# Cinematic dark theme (Qt stylesheet). Warm accent evokes "sound + film".
_STYLE = """
* { font-family: 'Inter', 'Helvetica Neue', Arial, sans-serif; color: #E8EAED; }
QWidget { background-color: #14161A; }
QLabel { background: transparent; }
#Title { font-size: 22px; font-weight: 700; color: #FFFFFF; }
#Subtitle { font-size: 12px; color: #9AA0A6; }
#SectionLabel { font-size: 11px; font-weight: 700; color: #FF7A59;
                text-transform: uppercase; letter-spacing: 1px; }
#LicenseBar { background-color: #1C1F24; border: 1px solid #2A2E35; border-radius: 10px; }
QComboBox, QLineEdit {
    background-color: #22262D; border: 1px solid #333842; border-radius: 8px;
    padding: 7px 10px; min-height: 20px; color: #E8EAED;
}
QComboBox:hover, QLineEdit:hover { border: 1px solid #FF7A59; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #22262D; border: 1px solid #333842; selection-background-color: #FF7A59;
}
QPushButton {
    background-color: #2A2E35; border: 1px solid #3A3F49; border-radius: 8px;
    padding: 9px 16px; font-weight: 600; color: #E8EAED;
}
QPushButton:hover { background-color: #343943; border: 1px solid #4A505B; }
QPushButton:pressed { background-color: #23272E; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #3A3F49; background: #22262D;
}
QCheckBox::indicator:checked { background: #FF7A59; border: 1px solid #FF7A59; }
QTextEdit {
    background-color: #0F1114; border: 1px solid #2A2E35; border-radius: 10px;
    color: #C5CAD1; font-family: 'SF Mono', 'Consolas', monospace; font-size: 12px;
}
#Status { color: #9AA0A6; font-size: 12px; }
#LicenseStatus { font-size: 12px; font-weight: 600; }
"""

# Inline stylesheet applied directly to the primary "Place SFX" button so it
# stands out without needing a distinct object name.
_PRIMARY_BTN = """
QPushButton {
    background-color: #FF7A59; border: 1px solid #FF7A59; color: #14161A;
    font-weight: 700; border-radius: 8px; padding: 9px 16px;
}
QPushButton:hover { background-color: #FF8C6E; }
QPushButton:pressed { background-color: #E86A4B; }
"""

_BRAINS = ["gemini", "openai", "claude"]
_SOUNDS = ["epidemic", "artlist", "audiio", "musicbed", "soundly", "freesound", "local"]
_SCOPES = [("Current clip", SELECT_CURRENT),
           ("Whole timeline", SELECT_ALL),
           ("Colored clips", SELECT_COLOR)]


def _get_ui_toolkit():
    """Return the (ui, dispatcher) pair from Resolve's Fusion UIManager."""
    fusion_obj = fusion
    if fusion_obj is None and bmd is not None:
        fusion_obj = bmd.scriptapp("Fusion")
    if fusion_obj is None:
        raise RuntimeError(
            "Fusion UIManager is unavailable. Run this from inside DaVinci Resolve."
        )
    ui = fusion_obj.UIManager
    dispatcher = bmd.UIDispatcher(ui)
    return ui, dispatcher


def _build_window(ui, dispatcher):
    """Construct and return the CineSFX window and its item map."""
    window = dispatcher.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "CineSFX",
            "Geometry": [180, 120, 600, 720],
            "StyleSheet": _STYLE,
        },
        ui.VGroup(
            {"Spacing": 12, "Weight": 1},
            [
                # Header
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"ID": "Title", "Text": "CineSFX"}),
                                ui.Label(
                                    {
                                        "ID": "Subtitle",
                                        "Text": "AI cinematic sound effects, "
                                        "in perfect sync.",
                                    }
                                ),
                            ],
                        ),
                    ],
                ),
                # License bar
                ui.HGroup(
                    {"ID": "LicenseBar", "Weight": 0, "Spacing": 8},
                    [
                        ui.Label({"ID": "LicenseStatus", "Text": "", "Weight": 1}),
                        ui.Button(
                            {"ID": "ToggleLicense", "Text": "Enter license", "Weight": 0}
                        ),
                    ],
                ),
                ui.HGroup(
                    {"ID": "LicenseRow", "Weight": 0, "Spacing": 8, "Hidden": True},
                    [
                        ui.LineEdit(
                            {
                                "ID": "LicenseKey",
                                "PlaceholderText": "Paste your CINESFX-1.… key",
                                "Weight": 1,
                            }
                        ),
                        ui.Button({"ID": "Activate", "Text": "Activate", "Weight": 0}),
                    ],
                ),
                # Engine section
                ui.Label({"ID": "SectionLabel", "Text": "Engine", "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Brain (AI)"}),
                                ui.ComboBox({"ID": "Brain"}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Sound library"}),
                                ui.ComboBox({"ID": "Sound"}),
                            ],
                        ),
                    ],
                ),
                ui.VGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"Text": "Local library folder (Soundly / Local only)"}),
                        ui.LineEdit(
                            {
                                "ID": "LibraryPath",
                                "PlaceholderText": "e.g. ~/Soundly/Library",
                            }
                        ),
                    ],
                ),
                # Scope section
                ui.Label({"ID": "SectionLabel", "Text": "What to score", "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Scope"}),
                                ui.ComboBox({"ID": "Scope"}),
                            ],
                        ),
                        ui.VGroup(
                            {"Weight": 1},
                            [
                                ui.Label({"Text": "Clip color (for 'Colored clips')"}),
                                ui.LineEdit({"ID": "Color", "Text": "Orange"}),
                            ],
                        ),
                    ],
                ),
                ui.CheckBox(
                    {
                        "ID": "DryRun",
                        "Text": "Preview only (free — no changes to the timeline)",
                        "Checked": True,
                        "Weight": 0,
                    }
                ),
                # Actions
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.Button({"ID": "Preview", "Text": "Preview (free)"}),
                        ui.Button(
                            {"ID": "Run", "Text": "Place SFX", "StyleSheet": _PRIMARY_BTN}
                        ),
                    ],
                ),
                ui.Label({"ID": "Status", "Text": "Ready.", "Weight": 0}),
                ui.TextEdit({"ID": "Output", "ReadOnly": True, "Text": "", "Weight": 1}),
            ],
        ),
    )

    items = window.GetItems()
    for value in _BRAINS:
        items["Brain"].AddItem(value)
    for value in _SOUNDS:
        items["Sound"].AddItem(value)
    for label, _mode in _SCOPES:
        items["Scope"].AddItem(label)
    return window, items


def _apply_settings_to_ui(items, settings: UserSettings) -> None:
    """Populate widgets from persisted settings."""
    if settings.brain and settings.brain in _BRAINS:
        items["Brain"].CurrentIndex = _BRAINS.index(settings.brain)
    if settings.sound_provider and settings.sound_provider in _SOUNDS:
        items["Sound"].CurrentIndex = _SOUNDS.index(settings.sound_provider)
    scope_values = [mode for _label, mode in _SCOPES]
    if settings.scope in scope_values:
        items["Scope"].CurrentIndex = scope_values.index(settings.scope)
    items["Color"].Text = settings.color or "Orange"
    items["DryRun"].Checked = bool(settings.dry_run)
    # Show whichever library path applies to the selected provider.
    provider = settings.sound_provider or "epidemic"
    lib = settings.provider_overrides.get(provider, {}).get("library_path", "")
    items["LibraryPath"].Text = lib or ""


def _read_settings_from_ui(items) -> UserSettings:
    """Build a UserSettings object from the current widget values."""
    settings = UserSettings.load()
    settings.brain = _BRAINS[items["Brain"].CurrentIndex]
    settings.sound_provider = _SOUNDS[items["Sound"].CurrentIndex]
    settings.scope = _SCOPES[items["Scope"].CurrentIndex][1]
    settings.color = items["Color"].Text or "Orange"
    settings.dry_run = bool(items["DryRun"].Checked)
    library_path = (items["LibraryPath"].Text or "").strip()
    if library_path and settings.sound_provider in ("soundly", "local"):
        settings.set_provider_override(settings.sound_provider, "library_path", library_path)
    return settings


def _run_pipeline(items, settings: UserSettings, dry_run: bool, ui_call) -> None:
    """Execute the pipeline for the given settings (runs off the UI thread)."""
    def status(text):
        ui_call(lambda: setattr(items["Status"], "Text", text))

    def append(text):
        def _do():
            existing = items["Output"].PlainText or ""
            items["Output"].PlainText = f"{existing}\n{text}" if existing else text
        ui_call(_do)

    try:
        status("Loading configuration…")
        config = load_config()  # user settings already overlaid here
        timeline_agent = TimelineAgent(
            sfx_track_name=str(config.placement().get("sfx_track_name", "CineSFX")),
            resolve_obj=resolve,
        )
        orchestrator = Orchestrator(config, timeline_agent=timeline_agent)
        results = orchestrator.run(
            mode=settings.scope,
            color=settings.color,
            dry_run=dry_run,
            progress=status,
        )
        append(orchestrator.report(results))
        verb = "Previewed" if dry_run else "Placed"
        status(f"{verb} SFX for {len(results)} clip(s).")
    except ConfigError as exc:
        status("Configuration error.")
        append(f"Configuration error: {exc}")
    except Exception as exc:  # noqa: BLE001 - show the error in the panel
        status("Error — see output below.")
        append(f"Error: {exc}\n{traceback.format_exc()}")


def main() -> None:
    """Show the CineSFX panel and run its event loop."""
    ui, dispatcher = _get_ui_toolkit()
    window, items = _build_window(ui, dispatcher)

    def ui_call(fn):
        # UIManager updates happen on the dispatcher thread; call directly.
        try:
            fn()
        except Exception:  # noqa: BLE001 - never let a UI update crash a worker
            pass

    def refresh_license():
        status = get_license_status()
        marker = "\u2713" if status.activated else "\u26a0"  # check / warning
        items["LicenseStatus"].Text = f"{marker}  {status.message}"

    # Load persisted choices.
    settings = UserSettings.load()
    _apply_settings_to_ui(items, settings)
    refresh_license()

    def on_close(_event):
        dispatcher.ExitLoop()

    def on_toggle_license(_event):
        items["LicenseRow"].Hidden = not items["LicenseRow"].Hidden

    def on_activate(_event):
        key = (items["LicenseKey"].Text or "").strip()
        try:
            result = activate_license(key)
            items["Status"].Text = result.message
        except Exception as exc:  # noqa: BLE001 - show a friendly message
            items["Status"].Text = f"Activation failed: {exc}"
        refresh_license()

    def start(dry_run):
        current = _read_settings_from_ui(items)
        current.save()  # remember the user's choices for next time
        items["Output"].PlainText = ""
        items["Status"].Text = "Working…"
        worker = threading.Thread(
            target=_run_pipeline,
            args=(items, current, dry_run, ui_call),
            daemon=True,
        )
        worker.start()

    def on_preview(_event):
        start(dry_run=True)

    def on_run(_event):
        start(dry_run=bool(items["DryRun"].Checked))

    window.On[WINDOW_ID].Close = on_close
    window.On.ToggleLicense.Clicked = on_toggle_license
    window.On.Activate.Clicked = on_activate
    window.On.Preview.Clicked = on_preview
    window.On.Run.Clicked = on_run

    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    main()
