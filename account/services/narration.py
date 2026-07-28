"""Server-side Auto-Narration composer.

Mirrors the sentence patterns of the client-side engine in
``account/templates/journal.html::buildAutoNarration()`` so the SAME wording can
be produced on the server — used by the ledger auto-posting service and any
other backend caller. Unlike the JS engine, this one actually honors the
``NarrationSettings`` toggles (enabled / include_amount / include_reference /
include_party), which were previously dead config.
"""
import re
from decimal import Decimal


def format_inr(amount):
    """₹ amount with Indian digit grouping (1,00,000.00), matching the JS
    ``formatINR`` (en-IN locale)."""
    try:
        n = Decimal(str(amount or 0))
    except Exception:
        n = Decimal("0")
    neg = n < 0
    n = abs(n)
    whole = int(n)
    dec = f"{(n - whole):.2f}"[2:]          # two decimal digits
    s = str(whole)
    if len(s) > 3:
        last3 = s[-3:]
        rest = s[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        grouped = ",".join(groups) + "," + last3
    else:
        grouped = s
    return ("-" if neg else "") + "₹" + grouped + "." + dec


def compose_narration(voucher_type, *, party_name=None, amount=None,
                      reference=None, mode=None, settings=None):
    """Compose an accounting narration sentence for `voucher_type`.

    Honors ``NarrationSettings``: returns "" when disabled, and drops the
    amount / reference / party fragments when their toggle is off. `settings`
    defaults to the singleton ``NarrationSettings.get_solo()``.
    """
    if settings is None:
        from account.models import NarrationSettings
        settings = NarrationSettings.get_solo()
    if settings is not None and not settings.enabled:
        return ""

    inc_amount = getattr(settings, "include_amount", True) if settings else True
    inc_ref = getattr(settings, "include_reference", True) if settings else True
    inc_party = getattr(settings, "include_party", True) if settings else True

    amt = format_inr(amount) if (amount is not None and inc_amount) else ""
    party = (party_name or "").strip() if inc_party else ""
    ref = (reference or "").strip() if inc_ref else ""
    ref_suffix = f" Ref: {ref}." if ref else ""
    vt = (voucher_type or "").strip().lower()

    if vt == "payment":
        who = f"to {party}" if party else ""
        via = f"through {mode}" if mode else ""
        body = f"Being payment{f' of {amt}' if amt else ''} made {who} {via}."
    elif vt == "receipt":
        who = f"from {party}" if party else ""
        via = f"through {mode}" if mode else ""
        body = f"Being receipt{f' of {amt}' if amt else ''} received {who} {via}."
    elif vt == "sales":
        body = (f"Being sale of goods{f' to {party}' if party else ''}"
                f"{f' amounting to {amt}' if amt else ''}.")
    elif vt == "purchase":
        body = (f"Being purchase of goods{f' from {party}' if party else ''}"
                f"{f' amounting to {amt}' if amt else ''}.")
    elif vt == "contra":
        body = (f"Being contra entry{f' of {amt}' if amt else ''}"
                f"{f' with {party}' if party else ''}.")
    else:  # Journal / anything else
        label = (voucher_type or "journal").strip().lower()
        body = (f"Being {label} entry{f' of {amt}' if amt else ''}"
                f"{f' with {party}' if party else ''}.")

    return re.sub(r"\s+", " ", (body + ref_suffix)).strip()
