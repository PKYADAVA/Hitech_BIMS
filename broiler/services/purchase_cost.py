"""What an item actually cost to buy.

The Growing Charge Statement values a batch at the rates agreed in the Growing
Charge Master — what the farmer is paid against. The Production P&L asks a
different question: what did this flock cost the company, in money it actually
spent. So nothing here reads a scheme, a price list or a standard rate. It
reads purchases.

Without lot tracking there is no way to say which sack of feed came from which
invoice, so consumption is valued at the weighted average of what was paid for
that item — total spent over total bought, up to the date in question. That is
the honest answer to "what did this cost": it moves with the real price the
company paid and needs no fiction about which physical bag was eaten.

Bounded by date so a flock is not valued at a price agreed after it was sold.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum

Q2 = Decimal("0.01")
ZERO = Decimal("0.00")


def purchase_rates(item_ids, on_or_before=None):
    """Weighted average purchase rate per item, as ``{item_id: Decimal}``.

    One query for the whole set rather than one per item: a batch's feed,
    medicine and chick lines together run to dozens of items, and a report that
    asks the database once per line is a report nobody waits for.

    An item never purchased is absent from the result rather than present as
    zero. Zero is a price; "we have no purchase to price this from" is not, and
    the caller has to be able to say so on the page instead of quietly showing
    a cost of nothing.
    """
    from purchase.models import GeneralPurchaseItem

    lines = GeneralPurchaseItem.objects.filter(item_id__in=list(item_ids))
    if on_or_before:
        lines = lines.filter(purchase__date__lte=on_or_before)

    rates = {}
    # Received, plus free goods. Free stock costs nothing and still sits in the
    # store, so counting it lowers what a unit of that item actually cost —
    # which is the figure this report is for. Sent quantity is what was ordered,
    # not what arrived, and pricing on it would flatter a short delivery.
    for row in (lines.values("item_id")
                     .annotate(spent=Sum("amount"),
                               received=Sum("rcv_qty"), free=Sum("free_qty"))):
        bought = Decimal(str(row["received"] or 0)) + Decimal(str(row["free"] or 0))
        if bought <= 0:
            # Purchased quantity nets to nothing — a return against its own
            # receipt, most often. There is no rate to be had from it, and a
            # division would only invent one.
            continue
        spent = Decimal(str(row["spent"] or 0))
        rates[row["item_id"]] = (spent / bought).quantize(Q2)
    return rates


def value_consumption(rows, rates, quantity_key="quantity", item_key="item_id"):
    """Cost a set of consumption rows at actual purchase rates.

    Returns ``(total, unpriced)`` — the money, and the items that had no
    purchase to price from. The caller shows the second: a total that quietly
    omits an item reads as a cheaper flock rather than an incomplete one, and
    that is the kind of wrong figure somebody makes a decision on.
    """
    total = ZERO
    unpriced = set()
    for row in rows:
        item_id = row.get(item_key)
        rate = rates.get(item_id)
        if rate is None:
            if item_id is not None:
                unpriced.add(item_id)
            continue
        total += Decimal(str(row.get(quantity_key) or 0)) * rate
    return total.quantize(Q2), unpriced
