"""Auto Title-Case formatting for Remarks / Narration free-text fields.

A single project-wide ``pre_save`` receiver formats every model's ``remarks``
and ``narration`` field just before it is written, so the rule applies uniformly
across all apps without touching each model/form.

Rules (see ``to_title_case``):
  * Capitalize the first letter of every word.
  * Words containing a digit — invoice/item/batch/vehicle/GSTIN codes — are kept
    UPPERCASE exactly as their characters, so codes read cleanly
    (``inv-2456`` -> ``INV-2456``, ``b240701`` -> ``B240701``).
  * Known finance abbreviations (RTGS, NEFT, GST, …) are kept UPPERCASE.
  * Extra/duplicate whitespace is collapsed to single spaces.

Examples:
  ``feed transferred from akbarpur warehouse to shed 3``
      -> ``Feed Transferred From Akbarpur Warehouse To Shed 3``
  ``payment against inv-2456 through rtgs``
      -> ``Payment Against INV-2456 Through RTGS``
"""
import re

from django.db.models.signals import pre_save
from django.dispatch import receiver

# Abbreviations kept fully uppercase — payment/finance terms that are virtually
# never used as ordinary words (so title-casing them would look wrong).
_ABBREVIATIONS = {
    "RTGS", "NEFT", "IMPS", "UPI", "GST", "GSTIN", "CGST", "SGST", "IGST",
    "TDS", "TCS", "HSN", "SAC", "IFSC", "MICR", "PAN", "DD", "CHQ", "EMI", "POS",
}
_HAS_DIGIT = re.compile(r"\d")

# The free-text fields to auto-format on every save. `narration` is deliberately
# EXCLUDED: accounting narration is composed by the Auto-Narration engine in
# sentence case (e.g. "Being purchase of goods from …"), and title-casing it on
# save would fight that engine. Remarks stay title-cased.
_TARGET_FIELDS = ("remarks",)


def to_title_case(text):
    """Return `text` Title-Cased with codes/abbreviations preserved uppercase and
    extra whitespace removed. Non-string / empty input is returned unchanged."""
    if not text or not isinstance(text, str):
        return text
    words = []
    for w in text.split():                       # split() drops extra whitespace
        if _HAS_DIGIT.search(w):
            words.append(w.upper())              # code: invoice / batch / vehicle / GSTIN
        elif w.upper() in _ABBREVIATIONS:
            words.append(w.upper())              # known abbreviation
        else:
            words.append(w[:1].upper() + w[1:].lower())  # ordinary word
    return " ".join(words)


@receiver(pre_save, dispatch_uid="titlecase_remarks_narration")
def _titlecase_text_fields(sender, instance, **kwargs):
    """Title-case `remarks` / `narration` on any model right before it saves."""
    for fname in _TARGET_FIELDS:
        val = getattr(instance, fname, None)
        if isinstance(val, str) and val.strip():
            formatted = to_title_case(val)
            if formatted != val:
                setattr(instance, fname, formatted)
