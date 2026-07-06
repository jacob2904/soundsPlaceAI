"""One-time, lifetime license verification (fully offline).

The plugin is sold as a single perpetual purchase — no subscriptions, no online
check on every launch. To support that cleanly we use **asymmetric signatures**:

* The vendor holds a private Ed25519 key and signs each customer's license.
* The plugin ships only the matching *public* key and verifies signatures
  locally. A license therefore cannot be forged without the private key, yet no
  secret is embedded in the distributed plugin and no license server is required.

A license string looks like::

    CINESFX-1.<base64url(payload_json)>.<base64url(signature)>

``payload`` carries the licensee, product, edition (``lifetime``) and issue date.
Lifetime licenses have no expiry. Verification is pure, offline, and cheap.

The vendor tooling to mint keys/licenses lives in ``tools/``.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

PREFIX = "CINESFX-1"
PRODUCT = "cinesfx"

# Public verification key (base64url of the 32-byte Ed25519 public key).
# Replace this with YOUR key for production (see tools/generate_keypair.py).
# It can also be overridden at runtime via the CINESFX_LICENSE_PUBLIC_KEY env var.
_DEFAULT_PUBLIC_KEY_B64 = "mf6B9kn3WBDcQruqt5z6t2UkIUpWkgZbM7mtOi4SdcM="


class LicenseError(RuntimeError):
    """Raised when a license is missing, malformed, or invalid."""


@dataclass(frozen=True)
class LicenseInfo:
    """A verified license's contents."""

    licensee: str
    edition: str
    issued: str
    license_id: str
    expires: Optional[str] = None

    @property
    def is_lifetime(self) -> bool:
        return self.edition.lower() == "lifetime" and not self.expires

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Return True if a dated license has passed its expiry."""
        if not self.expires:
            return False
        moment = now or datetime.now(timezone.utc)
        try:
            expiry = datetime.fromisoformat(self.expires)
        except ValueError:
            return True
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return moment > expiry

    def summary(self) -> str:
        """Return a short, human-readable one-line description."""
        kind = "Lifetime" if self.is_lifetime else f"until {self.expires}"
        return f"{self.licensee} — {self.edition} ({kind})"


def _public_key_b64() -> str:
    """Return the active public key, honouring the env override."""
    return os.environ.get("CINESFX_LICENSE_PUBLIC_KEY", _DEFAULT_PUBLIC_KEY_B64).strip()


def _b64url_decode(text: str) -> bytes:
    """Decode base64url text, tolerating missing padding."""
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _b64url_encode(data: bytes) -> str:
    """Encode bytes as unpadded base64url text."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_payload(
    licensee: str,
    edition: str = "lifetime",
    expires: Optional[str] = None,
    license_id: Optional[str] = None,
) -> dict[str, Any]:
    """Construct a license payload dict (used by the vendor signer).

    Args:
        licensee: Name/email the license is issued to.
        edition: Edition string; ``lifetime`` marks a perpetual license.
        expires: Optional ISO-8601 expiry (omit/None for lifetime).
        license_id: Optional stable id; a timestamp-based one is generated if
            omitted.

    Returns:
        A JSON-serialisable payload dictionary.
    """
    if not licensee.strip():
        raise LicenseError("licensee must not be empty.")
    return {
        "product": PRODUCT,
        "licensee": licensee.strip(),
        "edition": edition,
        "issued": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "expires": expires,
        "id": license_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
    }


def encode_license(payload: dict[str, Any], signature: bytes) -> str:
    """Assemble the final license string from a payload and its signature."""
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return f"{PREFIX}.{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def verify_license(license_str: str, public_key_b64: Optional[str] = None) -> LicenseInfo:
    """Verify a license string offline and return its contents.

    Args:
        license_str: The full license string.
        public_key_b64: Optional public key override (base64url); defaults to the
            embedded/env key. Mainly used for testing.

    Returns:
        A :class:`LicenseInfo` for a valid, unexpired, correct-product license.

    Raises:
        LicenseError: If the license is malformed, forged, expired, or for the
            wrong product.
    """
    if not license_str or not license_str.strip():
        raise LicenseError("No license key provided.")

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey,
        )
    except ImportError as exc:  # pragma: no cover - dependency guaranteed by reqs
        raise LicenseError(
            "The 'cryptography' package is required to verify licenses. "
            "Install it with: pip install cryptography"
        ) from exc

    parts = license_str.strip().split(".")
    if len(parts) != 3 or parts[0] != PREFIX:
        raise LicenseError("License key format is not recognised.")

    _, payload_b64, signature_b64 = parts
    try:
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(signature_b64)
        payload = json.loads(payload_bytes)
    except (ValueError, json.JSONDecodeError) as exc:
        raise LicenseError("License key is corrupted.") from exc

    key_b64 = public_key_b64 or _public_key_b64()
    try:
        public_key = Ed25519PublicKey.from_public_bytes(_b64url_decode(key_b64))
        # Re-serialise deterministically so we verify exactly what was signed.
        canonical = json.dumps(
            payload, separators=(",", ":"), sort_keys=True
        ).encode()
        public_key.verify(signature, canonical)
    except InvalidSignature as exc:
        raise LicenseError("License signature is invalid (key does not match).") from exc
    except (ValueError, TypeError) as exc:
        raise LicenseError(f"License could not be verified: {exc}") from exc

    if payload.get("product") != PRODUCT:
        raise LicenseError("License is for a different product.")

    info = LicenseInfo(
        licensee=str(payload.get("licensee", "")),
        edition=str(payload.get("edition", "unknown")),
        issued=str(payload.get("issued", "")),
        license_id=str(payload.get("id", "")),
        expires=payload.get("expires"),
    )
    if info.is_expired():
        raise LicenseError(f"License expired on {info.expires}.")
    return info
