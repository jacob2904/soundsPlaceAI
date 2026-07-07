# Developing soundsPlaceAI / CineSFX

This guide gets a new contributor productive fast: how the code is laid out, how to
run it and the tests, and how to extend the two pluggable layers (brains and sound
providers). For the *why* behind the design, read
[`ARCHITECTURE.md`](ARCHITECTURE.md).

## TL;DR

```bash
# 1. Create a virtualenv and install the package + dev tools
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"                       # editable install + pytest

# 2. Run the whole test suite (no DaVinci Resolve or API keys required)
python -m pytest -q

# 3. Try the CLI (works without Resolve for --doctor / library commands)
python -m scripts.run_cli --doctor
```

`ffmpeg`/`ffprobe` must be on your PATH for real analysis, but the unit tests don't
need them.

## The 10-minute mental model

The plugin is a **pipeline of small agents** wired together by an orchestrator:

```
TimelineAgent → SceneAgent → BrainAgent → SoundAgent → PlacementAgent
   (Resolve)     (analysis)    (LLM)      (SFX files)    (timeline edits)
```

- Every agent has **one job**, a **small typed interface**, and is **unit-tested in
  isolation**.
- The typed dataclasses in [`cinesfx/models.py`](../cinesfx/models.py)
  (`ClipSelection`, `Scene`, `SfxCue`, `SoundAsset`, `PlannedPlacement`, …) are the
  *contracts* that flow between agents. Read this file first — it's the shared
  vocabulary of the whole codebase.
- The two "pluggable" layers (**brain** and **sound**) each have an abstract base
  class + a factory. Adding a new one is a small, local change.

## Where everything lives

| Path | What it is |
|---|---|
| `cinesfx/orchestrator.py` | ★ Coordinates the pipeline: concurrency, batching, caching, dry-run, license gate, progress. Start here to trace a run. |
| `cinesfx/models.py` | Typed dataclasses passed between agents (the contracts). |
| `cinesfx/config.py` | Loads/validates `config.yaml`, overlays persisted user settings, reads secrets from env. |
| `cinesfx/settings.py` | Persistent, changeable end-user UI choices + license activation. |
| `cinesfx/user_store.py` | Cross-platform per-user config dir + tiny JSON read/write helpers. |
| `cinesfx/licensing.py` | Offline Ed25519 verification for one-time lifetime licenses. |
| `cinesfx/diagnostics.py` | The "Test connection" self-checks (Resolve, ffmpeg, keys, library, license). |
| `cinesfx/logging_utils.py` | Logging configured to redact secrets. |
| `cinesfx/resolve/` | `TimelineAgent` + connection — the **only** code that talks to Resolve. |
| `cinesfx/analysis/` | `SceneAgent` + `ffmpeg_utils` — shot detection and key-frame extraction. |
| `cinesfx/brain/` | Pluggable LLMs: `base.py`, `factory.py`, `gemini.py`, `openai_provider.py`, `claude.py`, `prompts.py`. |
| `cinesfx/sound/` | Pluggable SFX providers: `base.py`, `factory.py`, `cache.py`, plus one file per provider. |
| `cinesfx/library/` | The user's own sound-library **catalog** (a JSON index, no database). |
| `cinesfx/placement/` | `PlacementAgent` + `spatial.py` — timing, lanes, gain/pan/fades. |
| `plugin/CineSFX.py` | The DaVinci Resolve panel (Fusion UIManager). Thin: it reads settings and calls the orchestrator. |
| `scripts/run_cli.py` | Command-line entry point (also exposed as the `cinesfx` console script). |
| `tools/` | Vendor-only tooling to generate signing keypairs and mint licenses. |
| `tests/` | One `test_*.py` per module; runs without Resolve or network. |

## How to extend it

### Add a new "brain" (LLM)

1. Create `cinesfx/brain/<name>.py` with a class that subclasses
   `BrainProvider` (`cinesfx/brain/base.py`) and implements
   `describe_and_plan(scenes, context) -> list[SfxCue]`. Reuse
   `cinesfx/brain/prompts.py` to build the prompt and parse the strict-JSON reply.
2. Register it in `cinesfx/brain/factory.py` (one `if choice == "<name>"` branch,
   imported lazily so users only need the SDK they use).
3. Add `"<name>"` to `VALID_BRAINS` in `cinesfx/config.py`, and to `_BRAINS` in
   `plugin/CineSFX.py` and `_BRAIN_ENV` in `cinesfx/diagnostics.py` if it needs a key.
4. Add a test in `tests/` (mock the SDK; see existing brain tests for the pattern).

### Add a new sound provider

1. Create `cinesfx/sound/<name>.py` with a class that subclasses `SoundProvider`
   (`cinesfx/sound/base.py`) and implements:

   ```python
   def search(self, query, filters) -> list[SoundAsset]: ...
   def download(self, asset) -> Path: ...   # return a local file path
   ```

   Use `cinesfx/sound/cache.py` for content-addressed downloads. Because the rest of
   the pipeline only cares about the returned file, any provider is automatically
   "seamless with Resolve".
2. Register it in `cinesfx/sound/factory.py`, add `"<name>"` to
   `VALID_SOUND_PROVIDERS` in `cinesfx/config.py`, and to `_SOUNDS` in
   `plugin/CineSFX.py`. Wire a check into `cinesfx/diagnostics.py` (`check_sound`).
3. Document its real API capability in [`PROVIDERS.md`](PROVIDERS.md) and add a test
   (mock HTTP with `httpx.MockTransport`, or use a temp folder for local providers —
   see `tests/test_providers.py` and `tests/test_library_catalog.py`).

## Conventions

- **Typed dataclasses** for anything crossing an agent boundary (`models.py`).
- **Secrets only from the environment** (`.env`); never hard-code keys, and never log
  them (logging is redacted — see `logging_utils.py`).
- **Fail with clear, actionable errors.** Providers/agents raise their own error type
  (`SoundProviderError`, `BrainError`, `FfmpegError`, `ResolveConnectionError`,
  `ConfigError`, `LicenseError`) with a message that tells the user how to fix it.
- **No network/Resolve in unit tests.** Mock the boundary; keep tests fast and hermetic.
- **Lazy imports** for heavy/optional SDKs inside the factory branch that needs them.
- **Cross-platform paths** via `pathlib` / `os.path.expanduser`; no OS-specific
  assumptions.

## Running against DaVinci Resolve

Resolve's scripting API is only available inside Resolve (or with its environment
variables set). For real end-to-end runs:

- Install the panel per [`INSTALL.md`](INSTALL.md) (or run `scripts/run_cli.py` from a
  shell that has Resolve's scripting env configured).
- Use `--dry-run` / the panel's **Preview** to plan without editing the timeline.
- Use **Test connection** / `python -m scripts.run_cli --doctor` to check your setup.
