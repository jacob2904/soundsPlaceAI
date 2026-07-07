"""Connection registry + one-click connect logic for brains and sound sources.

This is the backend for the panel's **Connections** settings: a small, declarative
description of what each brain / sound provider needs to connect (an API key, an
OAuth id+secret, a local folder, or nothing), plus ``connect_*`` helpers that save
what the user entered and *verify* it by actually constructing the provider/brain.

Keeping the field metadata here (instead of hard-coding it in the UI) means the UI
stays dynamic and in sync: add a provider once, describe its fields, and the panel
renders the right inputs automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from cinesfx.config import AppConfig, load_config
from cinesfx.logging_utils import get_logger

_log = get_logger("connections")

# Field "kinds" that change how a value is stored/validated.
KIND_KEY = "key"        # one or more secret API keys (stored in the credential store)
KIND_OAUTH = "oauth"    # client id + secret (secrets)
KIND_FOLDER = "folder"  # a single local library folder (a setting, not a secret)
KIND_CATALOG = "catalog"  # one or more folders to index (a setting)
KIND_NONE = "none"      # nothing to connect


@dataclass(frozen=True)
class ConnField:
    """One input the user fills in to connect a provider/brain."""

    key: str                 # env-var name (secrets) or setting name (folders)
    label: str               # human label shown in the UI
    placeholder: str = ""    # example / hint text
    secret: bool = True      # mask in the UI + store in the credential store
    required: bool = True


@dataclass(frozen=True)
class Connection:
    """Everything the UI needs to render + connect one brain or sound source."""

    name: str
    label: str
    kind: str
    fields: tuple[ConnField, ...] = ()
    hint: str = ""           # e.g. where to get a key / which SDK to install

    @property
    def needs_input(self) -> bool:
        return bool(self.fields)


@dataclass(frozen=True)
class ConnectResult:
    """Outcome of a connect attempt or a status check."""

    ok: bool
    message: str


# --------------------------------------------------------------------- registry

BRAIN_CONNECTIONS: dict[str, Connection] = {
    "gemini": Connection(
        "gemini", "Google Gemini", KIND_KEY,
        (ConnField("GEMINI_API_KEY", "Gemini API key", "AIza…"),),
        hint="Free key at aistudio.google.com/apikey · needs 'google-generativeai'",
    ),
    "openai": Connection(
        "openai", "OpenAI (ChatGPT)", KIND_KEY,
        (ConnField("OPENAI_API_KEY", "OpenAI API key", "sk-…"),),
        hint="Key at platform.openai.com/api-keys · needs 'openai'",
    ),
    "claude": Connection(
        "claude", "Anthropic Claude", KIND_KEY,
        (ConnField("ANTHROPIC_API_KEY", "Anthropic API key", "sk-ant-…"),),
        hint="Key at console.anthropic.com · needs 'anthropic'",
    ),
}

SOUND_CONNECTIONS: dict[str, Connection] = {
    "epidemic": Connection(
        "epidemic", "Epidemic Sound", KIND_KEY,
        (
            ConnField("EPIDEMIC_API_KEY", "Epidemic API key", "bearer token"),
            ConnField(
                "EPIDEMIC_PARTNER_USER_ID", "Partner user id (optional)",
                "optional", secret=False, required=False,
            ),
        ),
        hint="Requires an Epidemic Sound partnership.",
    ),
    "freesound": Connection(
        "freesound", "Freesound (free)", KIND_KEY,
        (ConnField("FREESOUND_API_KEY", "Freesound API key", "free token"),),
        hint="Free key at freesound.org/apiv2/apply",
    ),
    "artlist": Connection(
        "artlist", "Artlist (Enterprise)", KIND_OAUTH,
        (
            ConnField("ARTLIST_CLIENT_ID", "Artlist Client ID", "client id"),
            ConnField("ARTLIST_CLIENT_SECRET", "Artlist Client Secret", "client secret"),
        ),
        hint="Enterprise OAuth creds from your Artlist manager (music today).",
    ),
    "audiio": Connection(
        "audiio", "Audiio (partner)", KIND_KEY,
        (
            ConnField("AUDIIO_API_BASE", "Audiio API base URL", "https://…", secret=False),
            ConnField("AUDIIO_API_TOKEN", "Audiio API token", "bearer token"),
        ),
        hint="No public API — partner/bespoke credentials only.",
    ),
    "musicbed": Connection(
        "musicbed", "Musicbed (partner)", KIND_KEY,
        (
            ConnField("MUSICBED_API_BASE", "Musicbed API base URL", "https://…", secret=False),
            ConnField("MUSICBED_API_TOKEN", "Musicbed API token", "bearer token"),
        ),
        hint="No public API — partner/bespoke credentials only.",
    ),
    "splice": Connection(
        "splice", "Splice (local folder)", KIND_FOLDER,
        (ConnField("library_path", "Splice folder", "~/Splice", secret=False, required=False),),
        hint="Reads samples synced by the Splice app (auto-detected if blank).",
    ),
    "soundly": Connection(
        "soundly", "Soundly (local library)", KIND_FOLDER,
        (ConnField("library_path", "Soundly library folder", "~/Soundly/Library", secret=False),),
        hint="Points at your local Soundly library folder.",
    ),
    "local": Connection(
        "local", "Local folder", KIND_FOLDER,
        (ConnField("library_path", "Folder of audio files", "~/SFX", secret=False),),
        hint="Any folder of audio files you own.",
    ),
    "catalog": Connection(
        "catalog", "My sound library (catalog)", KIND_CATALOG,
        (ConnField("roots", "Folder(s) to index (comma-separated)", "~/SFX, ~/Music/Sound Effects", secret=False),),
        hint="Index every sound on your computer, then place them offline.",
    ),
}


def brain_names() -> list[str]:
    return list(BRAIN_CONNECTIONS)


def sound_names() -> list[str]:
    return list(SOUND_CONNECTIONS)


# ------------------------------------------------------------------- connect ops


def _save_values(conn: Connection, values: dict[str, str]) -> dict[str, str]:
    """Persist entered values: secrets → credential store, settings → user settings.

    Returns the non-secret settings that were applied (for folder/catalog kinds).
    """
    from cinesfx.credentials import CredentialStore
    from cinesfx.settings import UserSettings

    secrets: dict[str, str] = {}
    settings_values: dict[str, str] = {}
    for spec in conn.fields:
        raw = (values.get(spec.key) or "").strip()
        if not raw:
            continue
        if spec.secret:
            secrets[spec.key] = raw
        else:
            settings_values[spec.key] = raw

    if secrets:
        CredentialStore().set_many(secrets)

    if settings_values:
        user = UserSettings.load()
        for key, raw in settings_values.items():
            if conn.kind == KIND_CATALOG and key == "roots":
                roots = [part.strip() for part in raw.split(",") if part.strip()]
                user.set_provider_override("catalog", "roots", roots)
            else:
                user.set_provider_override(conn.name, key, raw)
        user.save()
    return settings_values


def save_brain_inputs(name: str, values: dict[str, str]) -> None:
    """Persist entered brain credentials without verifying/selecting (best-effort)."""
    conn = BRAIN_CONNECTIONS.get(name)
    if conn is not None:
        _save_values(conn, values)


def save_sound_inputs(name: str, values: dict[str, str]) -> None:
    """Persist entered sound credentials/folders without verifying (best-effort)."""
    conn = SOUND_CONNECTIONS.get(name)
    if conn is not None:
        _save_values(conn, values)


def _config_for(*, brain: str | None = None, sound: str | None = None) -> AppConfig:
    """Load config and force a specific brain/sound choice for construction."""
    base = load_config()
    return AppConfig(
        brain=brain or base.brain,
        sound_provider=sound or base.sound_provider,
        raw=base.raw,
    )


def _verify(build: Callable[[], object], label: str) -> ConnectResult:
    """Run a provider/brain constructor and turn the result into a ConnectResult."""
    try:
        build()
    except Exception as exc:  # noqa: BLE001 - report any failure cleanly
        return ConnectResult(False, f"Not connected — {exc}")
    return ConnectResult(True, f"Connected to {label}.")


def connect_brain(name: str, values: dict[str, str]) -> ConnectResult:
    """Save the entered brain credentials, select the brain, and verify it."""
    conn = BRAIN_CONNECTIONS.get(name)
    if conn is None:
        return ConnectResult(False, f"Unknown brain '{name}'.")

    _save_values(conn, values)
    from cinesfx.settings import UserSettings

    user = UserSettings.load()
    user.brain = name
    user.save()

    from cinesfx.brain.factory import create_brain

    return _verify(lambda: create_brain(_config_for(brain=name)), conn.label)


def connect_sound(name: str, values: dict[str, str]) -> ConnectResult:
    """Save the entered sound credentials/folder, select it, and verify it."""
    conn = SOUND_CONNECTIONS.get(name)
    if conn is None:
        return ConnectResult(False, f"Unknown sound provider '{name}'.")

    _save_values(conn, values)
    from cinesfx.settings import UserSettings

    user = UserSettings.load()
    user.sound_provider = name
    user.save()

    from cinesfx.sound.factory import create_sound_provider

    return _verify(lambda: create_sound_provider(_config_for(sound=name)), conn.label)


def brain_status(name: str) -> ConnectResult:
    """Report whether ``name`` is currently connected (no changes made)."""
    conn = BRAIN_CONNECTIONS.get(name)
    if conn is None:
        return ConnectResult(False, f"Unknown brain '{name}'.")
    from cinesfx.brain.factory import create_brain

    return _verify(lambda: create_brain(_config_for(brain=name)), conn.label)


def sound_status(name: str) -> ConnectResult:
    """Report whether ``name`` is currently connected (no changes made)."""
    conn = SOUND_CONNECTIONS.get(name)
    if conn is None:
        return ConnectResult(False, f"Unknown sound provider '{name}'.")
    from cinesfx.sound.factory import create_sound_provider

    return _verify(lambda: create_sound_provider(_config_for(sound=name)), conn.label)
