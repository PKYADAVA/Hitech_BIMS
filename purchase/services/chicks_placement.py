"""Chicks bought straight onto a farm, and the Chicks Placement that says so.

Every placed-birds figure — Live Flock, a flock's age, the Daily Entry opening
count, the GC settlement, the dashboard and the alerts — reads a chick-category
stock transfer into the batch. So a Chicks Purchase line sent to a farm does
not try to be read in forty places: it creates that transfer, from the
warehouse the chicks were booked into, and keeps it in step with the line.

A purchase's lines are rewritten on every save, so the placements are matched
back to them in order and updated in place — the transfer keeps its number —
with any left over deleted. The running stock of each warehouse and item
touched is recomputed afterwards, as the Stock Transfer screens do.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError


def farm_line_errors(rows, batch_for_farm):
    """Rows naming a farm without what a placement needs, as messages.

    ``batch_for_farm(farm_id, batch_id)`` answers only a batch that farm runs.
    """
    from broiler.models import BroilerFarm

    problems = []
    for n, row in enumerate(rows, 1):
        farm_id = str(row.get("farm") or "")
        if not farm_id.isdigit():
            continue
        name = BroilerFarm.objects.filter(pk=farm_id).values_list("farm_name", flat=True).first() or "farm"
        if not row.get("farm_warehouse"):
            problems.append("row %d (%s): choose the warehouse the chicks come in through" % (n, name))
        if not batch_for_farm(int(farm_id), row.get("farm_batch")):
            problems.append("row %d (%s): select the flock / batch" % (n, name))
    return problems


def existing_placements(purchase):
    """The placements this purchase's lines hold now, in line order."""
    from inventory.models import StockTransfer

    ids = list(purchase.items.exclude(placement=None).order_by("id")
               .values_list("placement_id", flat=True))
    by_id = StockTransfer.objects.in_bulk(ids)
    return [by_id[i] for i in ids if i in by_id]


def sync(purchase, old_placements):
    """Give every farm line of ``purchase`` its placement; drop the rest.

    ``old_placements`` is what the lines held before they were rewritten
    (see existing_placements), reused in order so an edit keeps each
    transfer's number.
    """
    from inventory.models import StockTransfer
    from inventory.services.pricing import item_issue_price
    from inventory.views import _recompute_stock_transfer_chain

    touched = {(p.from_warehouse_id, p.item_id) for p in old_placements}
    spare = list(old_placements)
    price = item_issue_price(purchase.item, purchase.date) if purchase.item_id else None

    for line in purchase.items.exclude(farm=None).order_by("id"):
        st = spare.pop(0) if spare else StockTransfer()
        st._purchase_sync = True
        st.date = purchase.date
        st.dc_no = purchase.bill_no or ""
        st.item_id = purchase.item_id
        st.quantity = line.total_qty
        # The breakdown Chicks Placement records for reference, from the line.
        st.chicks_ordered = line.sent_qty
        st.transit_mortality = line.mortality
        st.shortage = line.shortage
        st.culls = line.weaks
        st.purchase_rate = line.rate or Decimal("0")
        st.rate = price if price is not None else Decimal("0")
        st.from_location_type, st.from_warehouse_id = "warehouse", line.farm_warehouse_id
        st.from_farm_id = st.from_batch_id = None
        st.to_location_type, st.to_farm_id, st.to_batch_id = "farm", line.farm_id, line.farm_batch_id
        st.to_warehouse_id = None
        st.source_supplier_id, st.source_hatchery_id = purchase.supplier_id, None
        st.vehicle_no = purchase.vehicle_no or ""
        st.driver_name = purchase.driver_name or ""
        st.remarks = "Placed by Chicks Purchase %s" % purchase.purchase_no
        try:
            st.full_clean(exclude=["trnum"])
        except ValidationError as e:
            farm = line.farm.farm_name if line.farm_id else "farm"
            raise ValidationError("Placement at %s: %s" % (farm, " ".join(e.messages)))
        st.save()
        line.placement = st
        line.save(update_fields=["placement"])
        touched.add((st.from_warehouse_id, st.item_id))

    for st in spare:
        st._purchase_sync = True
        st.delete()

    for warehouse_id, item_id in touched:
        _recompute_stock_transfer_chain("warehouse", warehouse_id, item_id)


def remove(purchase):
    """Delete every placement a purchase made — before the purchase goes."""
    from inventory.views import _recompute_stock_transfer_chain

    placements = existing_placements(purchase)
    touched = {(p.from_warehouse_id, p.item_id) for p in placements}
    for st in placements:
        st._purchase_sync = True
        st.delete()
    for warehouse_id, item_id in touched:
        _recompute_stock_transfer_chain("warehouse", warehouse_id, item_id)
