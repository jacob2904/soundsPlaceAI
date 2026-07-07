"""Vendor tool: mint a signed, one-time lifetime license for a customer.

The private key is read from the ``CINESFX_LICENSE_PRIVATE_KEY`` environment
variable (base64url of the 32-byte Ed25519 private key from generate_keypair.py).

Examples:
    export CINESFX_LICENSE_PRIVATE_KEY=...        # keep this secret!
    python tools/generate_license.py --licensee "ada@example.com"
    python tools/generate_license.py --licensee "Acme Studio" --expires 2027-01-01
"""

from __future__ import annotations

import argparse
import base64
import os
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Allow running from the repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cinesfx.licensing import build_payload, encode_license  # noqa: E402


def _load_private_key() -> Ed25519PrivateKey:
    raw_b64 = os.environ.get("CINESFX_LICENSE_PRIVATE_KEY", "").strip()
    if not raw_b64:
        raise SystemExit(
            "Set CINESFX_LICENSE_PRIVATE_KEY (from tools/generate_keypair.py)."
        )
    padding = "=" * (-len(raw_b64) % 4)
    return Ed25519PrivateKey.from_private_bytes(
        base64.urlsafe_b64decode(raw_b64 + padding)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a CineSFX license.")
    parser.add_argument("--licensee", required=True, help="Customer name or email.")
    parser.add_argument(
        "--edition", default="lifetime", help="Edition label (default: lifetime)."
    )
    parser.add_argument(
        "--expires",
        default=None,
        help="Optional ISO date (omit for a perpetual lifetime license).",
    )
    args = parser.parse_args()

    private_key = _load_private_key()
    payload = build_payload(
        licensee=args.licensee, edition=args.edition, expires=args.expires
    )
    import json

    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = private_key.sign(canonical)
    license_str = encode_license(payload, signature)

    print(license_str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
