"""Model fields that transparently encrypt their value at rest.

Reads decrypt automatically (``from_db_value``); writes encrypt
(``get_prep_value``). Application code, forms, and the admin only ever see
plaintext. Encrypted values cannot be filtered or ordered on — these fields
are for credentials, which are only ever read back whole.
"""

import logging

from django.db import models

from .crypto import TrackingCryptoError, decrypt, encrypt

logger = logging.getLogger("tracking.crypto")


class EncryptedTextField(models.TextField):
    """TextField whose value is Fernet-encrypted in the database.

    A TextField (not CharField) because ciphertext is longer than the
    plaintext and base64-encoded; there is no meaningful max_length.
    """

    description = "Text encrypted at rest (Fernet)"

    def from_db_value(self, value, expression, connection):  # pylint: disable=unused-argument
        if value is None:
            return value
        try:
            return decrypt(value)
        except TrackingCryptoError:
            # Surface as "credential missing" rather than a 500 on every page
            # that touches the row; the re-key procedure is in crypto.py.
            logger.exception(
                "Undecryptable credential in %s.%s — returning empty value.",
                self.model.__name__ if hasattr(self, "model") else "?",
                self.name,
            )
            return ""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return value
        return encrypt(str(value))
