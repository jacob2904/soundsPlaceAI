# Connecting your brain & audio (no `.env` editing)

CineSFX has a **Connections** panel so anyone can hook up their AI brain and their
sound source in a few clicks — pick from a dropdown, paste a key (or a folder),
and press **Connect**. No config files, no terminal.

## How it works

The panel's **Connections** section has two rows:

- **Brain (AI)** — choose Gemini, ChatGPT (OpenAI), or Claude.
- **Sound / audio source** — choose Epidemic, Freesound, Artlist, Audiio,
  Musicbed, Splice, Soundly, a local folder, or your own cataloged library.

The input fields update automatically for whatever you pick:

| You picked… | What you enter | Press |
|-------------|----------------|-------|
| Gemini / ChatGPT / Claude | the API key | **Connect** |
| Freesound / Epidemic | the API key | **Connect** |
| Artlist | Client ID **and** Client Secret | **Connect** |
| Audiio / Musicbed | the API base URL **and** token (partner-only) | **Connect** |
| Splice / Soundly / Local folder | the folder path | **Connect** |
| My sound library (catalog) | folder(s) to index (comma-separated) | **Connect**, then **Sync library** |

When you press **Connect**, CineSFX saves what you entered and immediately verifies
it by trying to reach that provider. A green check (✓) means you're connected; a
✗ shows a short reason if something's off. The status is re-checked every time you
open the panel, so you always know what's hooked up.

## Where do I get a key?

Each source shows a one-line hint under it. The quickest free path:

- **Brain:** Google Gemini — free key at
  [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
- **Sound:** Freesound — free key at
  [freesound.org/apiv2/apply](https://freesound.org/apiv2/apply).

That combination lets you preview and place sounds at zero cost.

## Is my key safe?

Yes. Keys you connect are stored in a single local file in your per-user config
directory (`connections.json`), written with owner-only permissions where the OS
supports it:

| OS | Location |
|----|----------|
| macOS | `~/Library/Application Support/cinesfx/connections.json` |
| Windows | `%APPDATA%\cinesfx\connections.json` |
| Linux | `~/.config/cinesfx/connections.json` |

- Keys are **never** printed, logged, or committed — logs are redacted.
- Nothing is uploaded anywhere except to the provider you connected to.
- The panel never displays a saved key back to you (it shows only the status).

## Prefer environment variables?

You still can. If a real environment variable (or a value in a `.env` file) is set
for a provider, it always **wins** over the stored key — so teams using a secret
manager keep working unchanged. The UI store is only a fallback for keys you
connect in the panel. The same stored keys also work from the CLI.

## Changing or removing a connection

- **Change:** pick the provider, enter the new key/folder, press **Connect** again.
- **Switch active source:** connecting a provider also selects it as the one used
  for the next run; your choice is remembered (see [SETTINGS.md](SETTINGS.md)).
- **Remove a key:** delete `connections.json` (or the single entry inside it) to
  clear stored credentials.
