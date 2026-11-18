import base64
import hashlib
import os

from nacl.secret import SecretBox


def _box() -> SecretBox:
    configured = os.getenv("REGISTRY_ENCRYPTION_KEY")
    if not configured:
        if os.getenv("DEMO_MODE", "false").casefold() != "true":
            raise RuntimeError("REGISTRY_ENCRYPTION_KEY is required outside demo mode")
        configured = "lifeline synthetic demo key - replace before deployment"
    try:
        raw = base64.urlsafe_b64decode(configured + "=" * (-len(configured) % 4))
        if len(raw) == SecretBox.KEY_SIZE:
            return SecretBox(raw)
    except ValueError:
        pass
    return SecretBox(hashlib.sha256(configured.encode()).digest())


def encrypt_registration(value: bytes) -> str:
    return base64.urlsafe_b64encode(bytes(_box().encrypt(value))).decode()


def decrypt_registration(value: str) -> bytes:
    try:
        encrypted = base64.urlsafe_b64decode(value.encode())
        return _box().decrypt(encrypted)
    except Exception as exc:
        raise ValueError("Household registration cannot be decrypted") from exc
