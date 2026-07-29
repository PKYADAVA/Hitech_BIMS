"""Item pricing lookups.

Kept out of views so model validation can use the same rule the form shows —
the price on screen and the price enforced on save can never diverge.
"""


def item_issue_price(item, on_date=None):
    """Issue price of an item from Item Price Master (Inventory > Master >
    Item Price List) — the most recent entry effective on or before the date.

    Returns None when the item has no such entry. Callers must treat that as
    "price not defined" rather than substituting a figure of their own: a
    transfer valued at a guessed rate would quietly feed a wrong number into
    stock valuation.
    """
    if not item:
        return None
    entries = item.price_list_entries.all()
    if on_date:
        entries = entries.filter(effective_date__lte=on_date)
    entry = entries.order_by("-effective_date", "-id").first()
    return entry.price if entry else None


def missing_price_message(item, on_date=None):
    """Message shown when an item has no price for the date."""
    as_on = " as on %s" % on_date.strftime("%d.%m.%Y") if on_date else ""
    return ("Item Price not defined for %s%s. Add one in "
            "Inventory > Master > Item Price List." % (item, as_on))
