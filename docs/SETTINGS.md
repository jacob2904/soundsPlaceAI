# Settings — pick once, change any time

Every choice you make in the panel (brain, sound library, scope, clip color,
local library folder, preview toggle) is **saved automatically** and restored the
next time you open CineSFX. You can change any of it whenever you want and the new
choice is remembered.

## Where settings live

A small JSON file in your per-user config directory:

| OS | Location |
|----|----------|
| macOS | `~/Library/Application Support/cinesfx/settings.json` |
| Windows | `%APPDATA%\cinesfx\settings.json` |
| Linux | `~/.config/cinesfx/settings.json` (respects `XDG_CONFIG_HOME`) |

Your activated license is stored alongside it in `license.json`, and any API keys
you connect in the panel live in `connections.json` (see
[CONNECTIONS.md](CONNECTIONS.md)). Override the directory with the
`CINESFX_CONFIG_DIR` environment variable (handy for testing).

## Precedence

Configuration is layered, lowest priority first:

1. `config.yaml` (advanced defaults you keep in the repo/project)
2. **User settings** saved by the panel (this file) — overrides `config.yaml`
3. Explicit CLI arguments for a single run

This means power users can keep detailed defaults in `config.yaml`, while the panel
drives the everyday choices — and the two never fight, because the panel simply
overlays the specific keys the user changed.

## What gets persisted

- `brain` (gemini / openai / claude)
- `sound_provider` (epidemic / freesound / artlist / audiio / musicbed / splice /
  soundly / local / catalog)
- `scope` (current / all / color) and `color`
- `dry_run` (preview toggle)
- Per-provider overrides, e.g. the Soundly/Local `library_path`
- Per-brain overrides, e.g. a specific model

## Editing by hand

The file is plain JSON, so you can edit or delete it. Deleting it simply resets the
panel to `config.yaml` defaults on next launch.
