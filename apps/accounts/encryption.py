"""Encryption helpers for OIDC client secrets."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
from django.conf import settings

# Prefix marks encrypted values and keeps encrypt_secret idempotent.
_ENC_PREFIX = "enc$"


def _get_fernet() -> Fernet:
    """Build a Fernet instance derived from settings.SECRET_KEY."""
    raw = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt plaintext and return enc$-prefixed ciphertext."""
    if not plaintext or plaintext.startswith(_ENC_PREFIX):
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode()).decode()
    return _ENC_PREFIX + token


def decrypt_secret(value: str) -> str:
    """Decrypt a value previously produced by encrypt_secret."""
    if not value:
        return value
    if not value.startswith(_ENC_PREFIX):
        raise ValueError(
            "decrypt_secret: value is missing the 'enc$' prefix. "
            "All secrets must be saved through OIDCProvider.save() so they are "
            "encrypted before being written to the database."
        )
    try:
        return _get_fernet().decrypt(value[len(_ENC_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Cannot decrypt client_secret - the value was encrypted with a "
            "different SECRET_KEY. Re-save the OIDC provider with the current "
            "client secret to fix this."
        ) from exc
