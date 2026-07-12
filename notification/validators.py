"""Validation and normalisation helpers for SMS recipients and messages.

Normalisation happens before a message ever reaches a provider so that invalid
input is rejected locally (and never retried) instead of wasting a provider
round-trip.
"""

import re

from .exceptions import SmsValidationError

# Digits only, optionally preceded by a single leading "+".
_ALLOWED_INPUT = re.compile(r"^\+?[0-9]+$")
# E.164 allows up to 15 digits; national numbers are at least 8 with country
# code applied. These bounds catch obvious typos without being India-specific.
_MIN_DIGITS = 10
_MAX_DIGITS = 15


def normalize_phone(raw, default_country_code):
    """Return a digits-only MSISDN with country code, or raise.

    Accepts common human formats (spaces, dashes, brackets, a leading ``+`` or
    ``00`` international prefix). A bare national number is prefixed with
    ``default_country_code``.

    Raises:
        SmsValidationError: if the number is empty or not a plausible MSISDN.
    """

    if raw is None:
        raise SmsValidationError("Phone number is required.")

    cleaned = re.sub(r"[\s\-()]", "", str(raw).strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    if not cleaned:
        raise SmsValidationError("Phone number is required.")
    if not _ALLOWED_INPUT.match(cleaned):
        raise SmsValidationError("Phone number contains invalid characters.")

    has_country_code = cleaned.startswith("+")
    digits = cleaned.lstrip("+")

    if not has_country_code and len(digits) <= _MIN_DIGITS:
        digits = f"{default_country_code}{digits}"

    if not digits.isdigit():
        raise SmsValidationError("Phone number must contain only digits.")
    if not _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
        raise SmsValidationError(
            f"Phone number must be between {_MIN_DIGITS} and {_MAX_DIGITS} digits."
        )
    return digits


def validate_message(message, max_length):
    """Return a stripped, non-empty message within ``max_length`` or raise.

    Raises:
        SmsValidationError: if the message is empty or too long.
    """

    if message is None:
        raise SmsValidationError("Message text is required.")

    text = str(message).strip()
    if not text:
        raise SmsValidationError("Message text is required.")
    if len(text) > max_length:
        raise SmsValidationError(
            f"Message exceeds the maximum length of {max_length} characters."
        )
    return text


def mask_phone(number):
    """Mask an MSISDN for logs, revealing only the last four digits."""

    if not number:
        return ""
    tail = str(number)[-4:]
    return f"{'*' * max(len(str(number)) - 4, 0)}{tail}"
