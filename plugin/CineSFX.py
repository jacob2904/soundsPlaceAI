"""CineSFX — DaVinci Resolve Workflow Integration / Script panel.

Drop this file into either:
  * the DaVinci Resolve "Workflow Integration Plugins" folder, or
  * the Resolve "Scripts/Utility" folder (then run from Workspace ▸ Scripts).

It shows a small UIManager window to pick the scope, the brain, and the sound
provider, then runs the CineSFX pipeline in a background thread so the UI stays
responsive. See docs/INSTALL.md for exact folder paths per OS.

When Resolve loads this script it injects the globals ``resolve``, ``fusion`` and
``bmd``; we use them directly and add the repository to ``sys.path`` so the
``cinesfx`` package can be imported.
"""

from __future__ import annotations

import os
import sys
import threading
import traceback

# --- Make the cinesfx package importable when run from Resolve ----------------
# Set CINESFX_HOME to this repository root, or edit the fallback path below.
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

# Resolve injects these globals; grab them defensively for standalone testing.
resolve = globals().get("resolve")
fusion = globals().get("fusion")
bmd = globals().get("bmd")

WINDOW_ID = "com.soundsplaceai.cinesfx"


def _get_ui_toolkit():
    """Return the (ui, dispatcher) pair from Resolve's Fusion UIManager."""
    fusion_obj = fusion
    if fusion_obj is None and bmd is not None:
        fusion_obj = bmd.scriptapp("Fusion")
    if fusion_obj is None:
        raise RuntimeError(
            "Fusion UIManager is unavailable. Run this from inside DaVinci Resolve "
            "(Workspace ▸ Scripts or Workflow Integrations)."
        )
    ui = fusion_obj.UIManager
    dispatcher = bmd.UIDispatcher(ui)
    return ui, dispatcher


def _build_window(ui, dispatcher):
    """Construct and return the CineSFX window."""
    combo_brains = ["(from config)", "gemini", "openai", "claude"]
    combo_sounds = [
        "(from config)",
        "epidemic",
        "artlist",
        "audiio",
        "musicbed",
        "soundly",
        "freesound",
        "local",
    ]

    window = dispatcher.AddWindow(
        {
            "ID": WINDOW_ID,
            "WindowTitle": "CineSFX — AI cinematic sound effects",
            "Geometry": [200, 200, 560, 560],
        },
        ui.VGroup(
            [
                ui.Label(
                    {
                        "Text": "Understand each scene, then place synced SFX.",
                        "Weight": 0,
                    }
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"Text": "Scope:", "Weight": 0.2}),
                        ui.ComboBox({"ID": "Scope", "Weight": 0.8}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"Text": "Brain:", "Weight": 0.2}),
                        ui.ComboBox({"ID": "Brain", "Weight": 0.8}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"Text": "Sounds:", "Weight": 0.2}),
                        ui.ComboBox({"ID": "Sound", "Weight": 0.8}),
                    ],
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Label({"Text": "Clip color:", "Weight": 0.2}),
                        ui.LineEdit(
                            {
                                "ID": "Color",
                                "Text": "Orange",
                                "PlaceholderText": "used when Scope = Colored clips",
                                "Weight": 0.8,
                            }
                        ),
                    ],
                ),
                ui.CheckBox(
                    {"ID": "DryRun", "Text": "Dry run (preview only)", "Checked": True}
                ),
                ui.HGroup(
                    {"Weight": 0},
                    [
                        ui.Button({"ID": "Run", "Text": "Analyse & place SFX"}),
                        ui.Button({"ID": "Close", "Text": "Close"}),
                    ],
                ),
                ui.Label({"ID": "Status", "Text": "Ready.", "Weight": 0}),
                ui.TextEdit(
                    {"ID": "Output", "ReadOnly": True, "Text": "", "Weight": 1}
                ),
            ]
        ),
    )

    items = window.GetItems()
    for label in ("Current clip", "Whole timeline", "Colored clips"):
        items["Scope"].AddItem(label)
    for brain in combo_brains:
        items["Brain"].AddItem(brain)
    for sound in combo_sounds:
        items["Sound"].AddItem(sound)
    return window, items


def _run_pipeline(items, set_status, append_output):
    """Execute the pipeline based on the current UI selections."""
    try:
        set_status("Loading configuration…")
        config = load_config()

        brain_choice = items["Brain"].CurrentText
        sound_choice = items["Sound"].CurrentText
        if brain_choice and brain_choice != "(from config)":
            config.brain = brain_choice
        if sound_choice and sound_choice != "(from config)":
            config.sound_provider = sound_choice

        scope_text = items["Scope"].CurrentText
        mode = SELECT_CURRENT
        color = None
        if scope_text == "Whole timeline":
            mode = SELECT_ALL
        elif scope_text == "Colored clips":
            mode = SELECT_COLOR
            color = items["Color"].Text or "Orange"

        dry_run = bool(items["DryRun"].Checked)

        timeline_agent = TimelineAgent(
            sfx_track_name=str(config.placement().get("sfx_track_name", "CineSFX")),
            resolve_obj=resolve,
        )
        orchestrator = Orchestrator(config, timeline_agent=timeline_agent)

        set_status("Analysing scenes & planning SFX… (this can take a moment)")
        results = orchestrator.run(mode=mode, color=color, dry_run=dry_run)
        append_output(orchestrator.report(results))
        verb = "Previewed" if dry_run else "Placed"
        set_status(f"{verb} SFX for {len(results)} clip(s). Done.")
    except ConfigError as exc:
        set_status("Configuration error.")
        append_output(f"Configuration error: {exc}")
    except Exception as exc:  # noqa: BLE001 - show the error in the panel
        set_status("Error — see output.")
        append_output(f"Error: {exc}\n{traceback.format_exc()}")


def main() -> None:
    """Show the CineSFX panel and run its event loop."""
    ui, dispatcher = _get_ui_toolkit()
    window, items = _build_window(ui, dispatcher)

    def set_status(text: str) -> None:
        items["Status"].Text = text

    def append_output(text: str) -> None:
        existing = items["Output"].PlainText or ""
        items["Output"].PlainText = f"{existing}\n{text}" if existing else text

    def on_close(_event) -> None:
        dispatcher.ExitLoop()

    def on_run(_event) -> None:
        items["Output"].PlainText = ""
        set_status("Working…")
        # Run off the UI thread so the panel stays responsive.
        worker = threading.Thread(
            target=_run_pipeline,
            args=(items, set_status, append_output),
            daemon=True,
        )
        worker.start()

    window.On[WINDOW_ID].Close = on_close
    window.On.Close.Clicked = on_close
    window.On.Run.Clicked = on_run

    window.Show()
    dispatcher.RunLoop()
    window.Hide()


if __name__ == "__main__":
    main()
