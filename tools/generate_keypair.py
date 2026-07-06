"""Vendor tool: generate an Ed25519 signing keypair for licensing.

Run this ONCE to create your own keys. Keep the private key secret (a password
manager or secret store). Paste the printed public key into
``cinesfx/licensing.py`` (``_DEFAULT_PUBLIC_KEY_B64``) or ship it via the
``CINESFX_LICENSE_PUBLIC_KEY`` environment variable.

    python tools/generate_keypair.py

The private key is what you use with tools/generate_license.py to mint licenses.
"""

from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def main() -> int:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    private_b64 = base64.urlsafe_b64encode(private_raw).decode("ascii")
    public_b64 = base64.urlsafe_b64encode(public_raw).decode("ascii")

    print("=== CineSFX licensing keypair ===")
    print("\nPUBLIC KEY (embed in cinesfx/licensing.py or CINESFX_LICENSE_PUBLIC_KEY):")
    print(public_b64)
    print("\nPRIVATE KEY (KEEP SECRET — used to sign licenses):")
    print(private_b64)
    print(
        "\nTip: export it before minting licenses:\n"
        "  export CINESFX_LICENSE_PRIVATE_KEY=" + public_b64[:6] + "…"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
