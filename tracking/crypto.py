"""Fernet encryption for tracking-provider credentials.

Every secret the tracking module stores (provider passwords, access tokens,
API keys, webhook secrets, map API keys) goes through :func:`encrypt` /
:func:`decrypt` — nothing credential-shaped is ever written to the database
in plaintext.

Key resolution:
    * ``TRACKING_ENCRYPTION_KEY`` (``.env``) — a standard urlsafe-base64
      32-byte Fernet key. Generate one with::

          python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

    * When unset, a key is derived from ``SECRET_KEY`` (SHA-256 → base64) so
      development works with zero extra setup. Production should set the
      dedicated key: with a derived key, rotating ``SECRET_KEY`` silently
      makes every stored credential undecryptable.

Ciphertext is stored with a ``fernet:`` prefix so a value can always be told
apart from legacy/imported plaintext, and re-keying scripts can find rows
that still need migrating.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

#: Prefix marking a value in the DB as Fernet ciphertext.
CIPHERTEXT_PREFIX = "fernet:"


class TrackingCryptoError(Exception):
    """Raised when stored ciphertext cannot be decrypted (wrong/rotated key)."""


def _fernet() -> Fernet:
    configured = getattr(settings, "TRACKING_ENCRYPTION_KEY", "") or ""
    if configured:
        return Fernet(configured.encode())
    derived = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(derived)


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext*; empty/None values pass through unchanged."""
    if not plaintext:
        return plaintext or ""
    return CIPHERTEXT_PREFIX + _fernet().encrypt(plaintext.encode()).decode()


def decrypt(value: str) -> str:
    """Decrypt a stored value.

    Values without the ``fernet:`` prefix are returned as-is (defensive:
    manually inserted or legacy plaintext should surface, not crash).
    Prefixed values that fail to decrypt raise :class:`TrackingCryptoError`
    so the caller can log a clear "re-enter credentials" message instead of
    silently using garbage.
    """
    if not value:
        return value or ""
    if not value.startswith(CIPHERTEXT_PREFIX):
        return value
    token = value[len(CIPHERTEXT_PREFIX):]
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise TrackingCryptoError(
            "Stored tracking credential could not be decrypted. The encryption "
            "key has changed (TRACKING_ENCRYPTION_KEY or a derived SECRET_KEY); "
            "re-enter the credential in Tracking Settings."
        ) from exc
