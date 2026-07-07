"""Tests for offline license signing + verification."""

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from cinesfx.licensing import (
    LicenseError,
    build_payload,
    encode_license,
    verify_license,
)


def _keypair():
    private = Ed25519PrivateKey.generate()
    pub_raw = private.public_key().public_bytes(
        encoding=__import__("cryptography").hazmat.primitives.serialization.Encoding.Raw,
        format=__import__(
            "cryptography"
        ).hazmat.primitives.serialization.PublicFormat.Raw,
    )
    return private, base64.urlsafe_b64encode(pub_raw).decode()


def _sign(private, payload) -> str:
    canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return encode_license(payload, private.sign(canonical))


def test_valid_lifetime_license_verifies():
    private, pub_b64 = _keypair()
    payload = build_payload("ada@example.com", edition="lifetime")
    license_str = _sign(private, payload)

    info = verify_license(license_str, public_key_b64=pub_b64)
    assert info.licensee == "ada@example.com"
    assert info.is_lifetime
    assert not info.is_expired()


def test_tampered_payload_is_rejected():
    private, pub_b64 = _keypair()
    payload = build_payload("ada@example.com")
    license_str = _sign(private, payload)

    prefix, payload_b64, sig = license_str.split(".")
    # Flip the licensee in the payload without re-signing.
    forged_payload = build_payload("evil@example.com")
    forged_bytes = json.dumps(
        forged_payload, separators=(",", ":"), sort_keys=True
    ).encode()
    forged_b64 = base64.urlsafe_b64encode(forged_bytes).decode().rstrip("=")
    forged = f"{prefix}.{forged_b64}.{sig}"

    with pytest.raises(LicenseError):
        verify_license(forged, public_key_b64=pub_b64)


def test_wrong_public_key_is_rejected():
    private, _pub_b64 = _keypair()
    _other, other_pub = _keypair()
    license_str = _sign(private, build_payload("ada@example.com"))
    with pytest.raises(LicenseError):
        verify_license(license_str, public_key_b64=other_pub)


def test_malformed_license_is_rejected():
    with pytest.raises(LicenseError):
        verify_license("not-a-license")
    with pytest.raises(LicenseError):
        verify_license("")


def test_expired_license_is_rejected():
    private, pub_b64 = _keypair()
    payload = build_payload("ada@example.com", edition="pro", expires="2000-01-01")
    license_str = _sign(private, payload)
    with pytest.raises(LicenseError):
        verify_license(license_str, public_key_b64=pub_b64)


def test_embedded_demo_key_roundtrip(monkeypatch):
    # The repo ships a demo keypair; verify a license minted with its private key
    # validates against the embedded public key.
    demo_private_b64 = "jrDMWPf7PHlQyX4uqt9wL4kS2ZvP_WnS7sbMsSEAVa8="
    private = Ed25519PrivateKey.from_private_bytes(
        base64.urlsafe_b64decode(demo_private_b64)
    )
    license_str = _sign(private, build_payload("demo@studio.com"))
    info = verify_license(license_str)  # uses embedded default public key
    assert info.licensee == "demo@studio.com"
