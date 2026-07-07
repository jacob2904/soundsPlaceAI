# Licensing — one-time purchase, lifetime

CineSFX is designed to be sold **once, for life** — no subscriptions and no
server that has to be online every time the user opens Resolve.

## How it works (offline, forgery-proof)

Licenses are **Ed25519-signed tokens**:

- You (the vendor) hold a private signing key.
- The plugin ships only the matching **public** key and verifies licenses locally.
- A license cannot be forged without your private key, yet the distributed plugin
  contains no secret and needs no license server.

A license looks like:

```
CINESFX-1.<base64url payload>.<base64url signature>
```

The payload records the licensee, product, edition (`lifetime`) and issue date.
Lifetime licenses never expire. Verification is offline and instant.

## What's free vs. licensed

- **Preview / dry-run is always free** — users see the full plan (scenes + the
  exact SFX and timings that would be placed). Great as a trial/funnel.
- **Placing SFX on the timeline requires an activated license.**

## For users: activating

- **Panel:** click **Enter license**, paste the key, **Activate**.
- **CLI:** `python -m scripts.run_cli --activate "CINESFX-1.…"`
- **Env / secret manager:** set `CINESFX_LICENSE_KEY`.

Check status any time: `python -m scripts.run_cli --license-status`.
The activated key is stored in the per-user config dir (see [`SETTINGS.md`](SETTINGS.md)).

## For you (the vendor): minting licenses

**1. Generate your own keypair once** (do NOT ship the repo's demo key to
production):

```bash
python tools/generate_keypair.py
```

Copy the printed **public** key into `cinesfx/licensing.py`
(`_DEFAULT_PUBLIC_KEY_B64`) or distribute it via the `CINESFX_LICENSE_PUBLIC_KEY`
environment variable. Store the **private** key somewhere safe (secret manager).

**2. Mint a license per customer** (e.g. from your checkout webhook):

```bash
export CINESFX_LICENSE_PRIVATE_KEY="…your private key…"
python tools/generate_license.py --licensee "buyer@example.com"
# prints the CINESFX-1.… key to email to the customer
```

You can also issue time-limited keys (e.g. for reviewers) with
`--expires 2027-01-01`.

## Selling it (integration ideas)

Because activation is just "verify a signed string", it drops into any store:

- **Gumroad / Lemon Squeezy / Paddle / Stripe:** on a successful one-time payment,
  call `tools/generate_license.py` (or the `cinesfx.licensing` functions) in your
  fulfilment webhook and email the key. No license server to run.

## Honest security notes

- This model proves a key is genuine and unmodified. Like any key-based scheme, a
  determined user could share a key; because it is not hardware-bound, it is
  **transferable** by design (simple and privacy-friendly).
- If you later want per-machine binding or revocation, add an optional online
  activation that records a machine id against the license id — the signed-token
  foundation here supports layering that on without changing the format.
- The repository ships a **demo** keypair purely so the code is testable end-to-end.
  Always replace it with your own before selling.
