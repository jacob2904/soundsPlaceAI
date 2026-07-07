"""CineSFX — DaVinci Resolve Workflow Integration / Script panel.

A polished, easy-to-use panel with a **Connections** area so the end user can
connect their AI "brain" (Gemini / ChatGPT / Claude) and their audio source
(Epidemic, Freesound, Artlist, Splice, Soundly, a local folder, or their own
cataloged library) straight from dropdowns + a **Connect** button — no manual
``.env`` editing. The right input fields appear dynamically for whatever the user
picks, credentials are saved securely, and every choice is remembered.

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
from cinesfx.connections import (  # noqa: E402
    BRAIN_CONNECTIONS,
    KIND_CATALOG,
    KIND_FOLDER,
    SOUND_CONNECTIONS,
    brain_status,
    connect_brain,
    connect_sound,
    save_brain_inputs,
    save_sound_inputs,
    sound_status,
)
from cinesfx.diagnostics import run_diagnostics, summarize  # noqa: E402
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
#Hint { font-size: 11px; color: #7C828B; }
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
#ConnStatus { font-size: 12px; font-weight: 600; }
#LicenseStatus { font-size: 12px; font-weight: 600; }
"""

_PRIMARY_BTN = """
QPushButton {
    background-color: #FF7A59; border: 1px solid #FF7A59; color: #14161A;
    font-weight: 700; border-radius: 8px; padding: 9px 16px;
}
QPushButton:hover { background-color: #FF8C6E; }
QPushButton:pressed { background-color: #E86A4B; }
"""

_CONNECT_BTN = """
QPushButton {
    background-color: #2C7A5B; border: 1px solid #2C7A5B; color: #F2FFF9;
    font-weight: 700; border-radius: 8px; padding: 9px 16px;
}
QPushButton:hover { background-color: #34906B; }
QPushButton:pressed { background-color: #256B4F; }
"""

# Order the dropdowns from the single source of truth (the connection registry).
_BRAINS = list(BRAIN_CONNECTIONS)
_SOUNDS = list(SOUND_CONNECTIONS)
_SCOPES = [("Current clip", SELECT_CURRENT),
           ("Whole timeline", SELECT_ALL),
           ("Colored clips", SELECT_COLOR)]

_CHECK = "\u2713"   # ✓
_CROSS = "\u2717"   # ✗
_DOT = "\u2022"     # •


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


def _set(items, item_id, attr, value):
    """Set a UI attribute defensively (ignores unsupported attrs/ids)."""
    try:
        setattr(items[item_id], attr, value)
    except Exception:  # noqa: BLE001 - UI is best-effort; never crash on a set
        pass


def _build_window(ui, dispatcher):
    """Construct and return the CineSFX window and its item map."""
    window = dispatcher.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "CineSFX",
            "Geometry": [160, 100, 620, 820],
            "StyleSheet": _STYLE,
        },
        ui.VGroup(
            {"Spacing": 10, "Weight": 1},
            [
                # Header
                ui.VGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"ID": "Title", "Text": "CineSFX"}),
                        ui.Label(
                            {
                                "ID": "Subtitle",
                                "Text": "AI cinematic sound effects, in perfect sync.",
                            }
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
                # ---------------------------------------------------- Connections
                ui.Label({"ID": "SectionLabel", "Text": "Connections", "Weight": 0}),
                # Brain
                ui.Label({"Text": "Brain (AI)", "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 8},
                    [
                        ui.ComboBox({"ID": "Brain", "Weight": 1}),
                        ui.LineEdit(
                            {"ID": "BrainKey", "PlaceholderText": "API key", "Weight": 2}
                        ),
                        ui.Button(
                            {"ID": "ConnectBrain", "Text": "Connect",
                             "StyleSheet": _CONNECT_BTN, "Weight": 0}
                        ),
                    ],
                ),
                ui.Label({"ID": "BrainStatus", "Text": "", "Weight": 0}),
                ui.Label({"ID": "BrainHint", "Text": "", "Weight": 0}),
                # Sound
                ui.Label({"Text": "Sound / audio source", "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 8},
                    [
                        ui.ComboBox({"ID": "Sound", "Weight": 1}),
                        ui.LineEdit(
                            {"ID": "SoundKey", "PlaceholderText": "API key / folder",
                             "Weight": 2}
                        ),
                        ui.Button(
                            {"ID": "ConnectSound", "Text": "Connect",
                             "StyleSheet": _CONNECT_BTN, "Weight": 0}
                        ),
                    ],
                ),
                ui.HGroup(
                    {"ID": "SoundSecretRow", "Weight": 0, "Spacing": 8, "Hidden": True},
                    [
                        ui.LineEdit(
                            {"ID": "SoundSecret", "PlaceholderText": "", "Weight": 1}
                        ),
                    ],
                ),
                ui.HGroup(
                    {"ID": "SoundLibRow", "Weight": 0, "Spacing": 8, "Hidden": True},
                    [
                        ui.Button(
                            {"ID": "CheckLibrary", "Text": "Check for changes", "Weight": 0}
                        ),
                        ui.Button(
                            {"ID": "SyncLibrary", "Text": "Sync library", "Weight": 0}
                        ),
                    ],
                ),
                ui.Label({"ID": "SoundStatus", "Text": "", "Weight": 0}),
                ui.Label({"ID": "SoundHint", "Text": "", "Weight": 0}),
                # ---------------------------------------------------- What to score
                ui.Label({"ID": "SectionLabel", "Text": "What to score", "Weight": 0}),
                ui.HGroup(
                    {"Weight": 0, "Spacing": 10},
                    [
                        ui.VGroup(
                            {"Weight": 1},
                            [ui.Label({"Text": "Scope"}), ui.ComboBox({"ID": "Scope"})],
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
                        ui.Button({"ID": "TestConn", "Text": "Test connection"}),
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


# ---------------------------------------------------------------- dynamic fields


def _brain_name(items) -> str:
    return _BRAINS[items["Brain"].CurrentIndex]


def _sound_name(items) -> str:
    return _SOUNDS[items["Sound"].CurrentIndex]


def _placeholder(f) -> str:
    return f"{f.label} — {f.placeholder}" if f.placeholder else f.label


def _configure_brain_fields(items) -> None:
    """Update the brain credential field to match the selected brain."""
    conn = BRAIN_CONNECTIONS[_brain_name(items)]
    field = conn.fields[0]
    _set(items, "BrainKey", "PlaceholderText", _placeholder(field))
    _set(items, "BrainKey", "EchoMode", "Password")
    _set(items, "BrainKey", "Text", "")
    _set(items, "BrainHint", "Text", conn.hint)


def _configure_sound_fields(items) -> None:
    """Show the right input(s) for the selected sound source."""
    conn = SOUND_CONNECTIONS[_sound_name(items)]
    fields = conn.fields

    if fields:
        f0 = fields[0]
        _set(items, "SoundKey", "Hidden", False)
        _set(items, "SoundKey", "PlaceholderText", _placeholder(f0))
        _set(items, "SoundKey", "EchoMode", "Password" if f0.secret else "Normal")
    else:
        _set(items, "SoundKey", "Hidden", True)

    if len(fields) >= 2:
        f1 = fields[1]
        _set(items, "SoundSecretRow", "Hidden", False)
        _set(items, "SoundSecret", "PlaceholderText", _placeholder(f1))
        _set(items, "SoundSecret", "EchoMode", "Password" if f1.secret else "Normal")
        _set(items, "SoundSecret", "Text", "")
    else:
        _set(items, "SoundSecretRow", "Hidden", True)
        _set(items, "SoundSecret", "Text", "")

    _set(items, "SoundLibRow", "Hidden", conn.kind != KIND_CATALOG)
    _set(items, "SoundHint", "Text", conn.hint)
    _prefill_sound_primary(items, conn)


def _prefill_sound_primary(items, conn) -> None:
    """Prefill the folder/roots for local providers; never prefill secrets."""
    text = ""
    if conn.kind in (KIND_FOLDER, KIND_CATALOG):
        overrides = UserSettings.load().provider_overrides.get(conn.name, {})
        if conn.kind == KIND_CATALOG:
            roots = overrides.get("roots") or []
            text = ", ".join(roots) if isinstance(roots, list) else str(roots)
        else:
            text = overrides.get("library_path", "") or ""
    _set(items, "SoundKey", "Text", text)


def _status_line(result) -> str:
    marker = _CHECK if result.ok else _CROSS
    return f"{marker}  {result.message}"


# ---------------------------------------------------------------- settings <-> UI


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
    _configure_brain_fields(items)
    _configure_sound_fields(items)


def _read_settings_from_ui(items) -> UserSettings:
    """Build a UserSettings object from the current widget values."""
    settings = UserSettings.load()
    settings.brain = _brain_name(items)
    settings.sound_provider = _sound_name(items)
    settings.scope = _SCOPES[items["Scope"].CurrentIndex][1]
    settings.color = items["Color"].Text or "Orange"
    settings.dry_run = bool(items["DryRun"].Checked)
    # Persist a typed folder/roots so a run works even before clicking Connect.
    conn = SOUND_CONNECTIONS.get(settings.sound_provider)
    primary = (items["SoundKey"].Text or "").strip()
    if conn and primary and conn.kind == KIND_CATALOG:
        roots = [part.strip() for part in primary.split(",") if part.strip()]
        settings.set_provider_override("catalog", "roots", roots)
    elif conn and primary and conn.kind == KIND_FOLDER:
        settings.set_provider_override(settings.sound_provider, "library_path", primary)
    return settings


def _persist_inputs(items) -> None:
    """Save typed credentials/folders for the selected brain + sound (best-effort)."""
    bconn = BRAIN_CONNECTIONS[_brain_name(items)]
    save_brain_inputs(_brain_name(items), {bconn.fields[0].key: items["BrainKey"].Text})

    sconn = SOUND_CONNECTIONS[_sound_name(items)]
    values = {}
    if sconn.fields:
        values[sconn.fields[0].key] = items["SoundKey"].Text
    if len(sconn.fields) >= 2:
        values[sconn.fields[1].key] = items["SoundSecret"].Text
    save_sound_inputs(_sound_name(items), values)


# --------------------------------------------------------------------- workers


def _sync_library(items, ui_call, dry_run: bool) -> None:
    """Index or resync the user's own sound library (off the UI thread)."""
    def status(text):
        ui_call(lambda: setattr(items["Status"], "Text", text))

    def append(text):
        def _do():
            existing = items["Output"].PlainText or ""
            items["Output"].PlainText = f"{existing}\n{text}" if existing else text
        ui_call(_do)

    try:
        from cinesfx.sound.base import SoundProviderError
        from cinesfx.sound.catalog import CatalogProvider

        config = load_config()
        settings = dict(config.raw.get("sound_providers", {}).get("catalog", {}))
        provider = CatalogProvider(settings, config.cache_dir())
        status("Checking your library for changes…" if dry_run else "Syncing your sound library…")
        try:
            stats = provider.scan(progress=append, dry_run=dry_run)
        except SoundProviderError as exc:
            status("No library folders set.")
            append(f"{exc}")
            return
        append(stats.summary())
        if dry_run and not stats.in_sync:
            status(
                f"{stats.changed} change(s) on disk — click 'Sync library' "
                f"(+{stats.added} ~{stats.updated} -{stats.removed})."
            )
        elif dry_run:
            status(f"Up to date — {stats.total} sound(s), no changes.")
        elif stats.in_sync:
            status(f"Already in sync — {stats.total} sound(s).")
        else:
            status(
                f"Resynced: +{stats.added} ~{stats.updated} -{stats.removed} "
                f"({stats.total} total)."
            )
    except ConfigError as exc:
        status("Configuration error.")
        append(f"Configuration error: {exc}")
    except Exception as exc:  # noqa: BLE001 - show the error in the panel
        status("Sync error — see output below.")
        append(f"Error: {exc}\n{traceback.format_exc()}")


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
        config = load_config()  # user settings + saved credentials already overlaid
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
        try:
            fn()
        except Exception:  # noqa: BLE001 - never let a UI update crash a worker
            pass

    def refresh_license():
        status = get_license_status()
        marker = _CHECK if status.activated else "\u26a0"
        items["LicenseStatus"].Text = f"{marker}  {status.message}"

    def refresh_brain_status():
        name = _brain_name(items)
        items["BrainStatus"].Text = f"{_DOT}  Checking {name}…"

        def work():
            result = brain_status(name)
            ui_call(lambda: setattr(items["BrainStatus"], "Text", _status_line(result)))

        threading.Thread(target=work, daemon=True).start()

    def refresh_sound_status():
        name = _sound_name(items)
        items["SoundStatus"].Text = f"{_DOT}  Checking {name}…"

        def work():
            result = sound_status(name)
            ui_call(lambda: setattr(items["SoundStatus"], "Text", _status_line(result)))

        threading.Thread(target=work, daemon=True).start()

    # Load persisted choices + configure the dynamic fields, then check status.
    settings = UserSettings.load()
    _apply_settings_to_ui(items, settings)
    refresh_license()
    refresh_brain_status()
    refresh_sound_status()

    # --------------------------------------------------------------- handlers

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

    def on_brain_changed(_event):
        _configure_brain_fields(items)
        refresh_brain_status()

    def on_sound_changed(_event):
        _configure_sound_fields(items)
        refresh_sound_status()

    def on_connect_brain(_event):
        name = _brain_name(items)
        conn = BRAIN_CONNECTIONS[name]
        values = {conn.fields[0].key: items["BrainKey"].Text or ""}
        items["BrainStatus"].Text = f"{_DOT}  Connecting to {conn.label}…"

        def work():
            result = connect_brain(name, values)
            ui_call(lambda: setattr(items["BrainStatus"], "Text", _status_line(result)))
            ui_call(lambda: setattr(items["BrainKey"], "Text", ""))

        threading.Thread(target=work, daemon=True).start()

    def on_connect_sound(_event):
        name = _sound_name(items)
        conn = SOUND_CONNECTIONS[name]
        values = {}
        if conn.fields:
            values[conn.fields[0].key] = items["SoundKey"].Text or ""
        if len(conn.fields) >= 2:
            values[conn.fields[1].key] = items["SoundSecret"].Text or ""
        items["SoundStatus"].Text = f"{_DOT}  Connecting to {conn.label}…"

        def work():
            result = connect_sound(name, values)
            ui_call(lambda: setattr(items["SoundStatus"], "Text", _status_line(result)))
            # Keep folder text visible; only clear secret fields after connecting.
            if conn.kind not in (KIND_FOLDER, KIND_CATALOG):
                ui_call(lambda: setattr(items["SoundKey"], "Text", ""))
            ui_call(lambda: setattr(items["SoundSecret"], "Text", ""))

        threading.Thread(target=work, daemon=True).start()

    def start(dry_run):
        _read_settings_from_ui(items).save()
        _persist_inputs(items)
        current = _read_settings_from_ui(items)
        items["Output"].PlainText = ""
        items["Status"].Text = "Working…"
        threading.Thread(
            target=_run_pipeline,
            args=(items, current, dry_run, ui_call),
            daemon=True,
        ).start()

    def on_preview(_event):
        start(dry_run=True)

    def on_run(_event):
        start(dry_run=bool(items["DryRun"].Checked))

    def _test_connection():
        try:
            config = load_config()
        except ConfigError:
            config = None
        results = run_diagnostics(config=config, resolve_obj=resolve)
        report = summarize(results)
        ok = all(result.ok for result in results)
        ui_call(lambda: setattr(items["Output"], "PlainText", report))
        ui_call(
            lambda: setattr(
                items["Status"],
                "Text",
                "All checks passed." if ok else "Some checks need attention.",
            )
        )

    def on_test(_event):
        items["Output"].PlainText = ""
        items["Status"].Text = "Testing connection…"
        threading.Thread(target=_test_connection, daemon=True).start()

    def _start_library(dry_run):
        _read_settings_from_ui(items).save()
        items["Output"].PlainText = ""
        items["Status"].Text = "Checking for changes…" if dry_run else "Syncing library…"
        threading.Thread(
            target=_sync_library, args=(items, ui_call, dry_run), daemon=True
        ).start()

    def on_check(_event):
        _start_library(dry_run=True)

    def on_sync(_event):
        _start_library(dry_run=False)

    window.On[WINDOW_ID].Close = on_close
    window.On.ToggleLicense.Clicked = on_toggle_license
    window.On.Activate.Clicked = on_activate
    window.On.Brain.CurrentIndexChanged = on_brain_changed
    window.On.Sound.CurrentIndexChanged = on_sound_changed
    window.On.ConnectBrain.Clicked = on_connect_brain
    window.On.ConnectSound.Clicked = on_connect_sound
    window.On.CheckLibrary.Clicked = on_check
    window.On.SyncLibrary.Clicked = on_sync
    window.On.TestConn.Clicked = on_test
    window.On.Preview.Clicked = on_preview
    window.On.Run.Clicked = on_run

    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    main()
