"""Coordinator-only payload encryption using libsodium sealed boxes."""

import base64
import json
import os
from typing import Any

from nacl.public import PrivateKey, SealedBox

ALGORITHM = "libsodium-sealed-box-v1"


def _secret_key() -> PrivateKey | None:
    encoded = os.getenv("COORDINATOR_SECRET_KEY", "").strip()
    if not encoded:
        return None
    raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    if len(raw) != PrivateKey.SIZE:
        raise ValueError("COORDINATOR_SECRET_KEY must encode exactly 32 bytes")
    return PrivateKey(raw)


def coordinator_public_key() -> str | None:
    secret = _secret_key()
    if secret is None:
        return None
    return base64.urlsafe_b64encode(bytes(secret.public_key)).decode("ascii").rstrip("=")


def open_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Decrypt sealed event content for triage; leave legacy plaintext events intact."""
    sealed = payload.get("_sealed_payload")
    if sealed is None:
        return payload
    if not isinstance(sealed, dict) or sealed.get("version") != 1 or sealed.get("algorithm") != ALGORITHM:
        raise ValueError("unsupported sealed payload format")
    secret = _secret_key()
    if secret is None:
        raise ValueError("coordinator decryption key is not configured")
    encoded = sealed.get("ciphertext")
    if not isinstance(encoded, str):
        raise TypeError("sealed payload ciphertext is missing")
    try:
        ciphertext = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        plaintext = SealedBox(secret).decrypt(ciphertext)
        result = json.loads(plaintext)
    except Exception as exc:
        raise ValueError("sealed payload could not be decrypted") from exc
    if not isinstance(result, dict):
        raise TypeError("sealed payload must contain a JSON object")
    return result
