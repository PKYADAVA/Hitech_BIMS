"""What is happening on a farm right now, for the Farmers & Farms lists.

The master page could say how big a farm was but not whether birds were on it,
so deciding where to place the next flock meant leaving the page and opening
the flock screens one farm at a time.

Everything here is derived from records that already exist — open batches,
chick placements, the daily losses and the bird sales booked against them — so
there is no new figure to keep in step with the ones the flock screens show.
The rules match ``_flock_counts`` and ``_placement_date`` in ``broiler.views``
deliberately: a farm that reads "1,240 live" here must read the same there.

Written as bulk lookups keyed by farm rather than per-farm helpers, because the
list asks for every farm at once and the per-batch versions would each cost a
query.
"""
from datetime import date

from django.db.models import Count, Min, Sum

from broiler.models import BirdSale, BroilerBatch, BroilerFarmShed, DailyEntry


def _sum_by(rows, key, *fields):
    """{key: {field: total}} from a values().annotate() result."""
    return {row[key]: {f: row.get(f) for f in fields} for row in rows}


def farm_occupancy(farm_ids=None, today=None):
    """{farm_id: {...}} — the flock on each farm, or why there isn't one.

    A farm normally holds one open batch, but nothing stops it holding two, so
    the live count is the total across all of them and ``open_batches`` says
    how many there were. ``vacant_since`` is only meaningful when there is no
    open batch; it is the day the last flock left.
    """
    from inventory.item_families import chick_items
    from inventory.models import StockTransfer

    today = today or date.today()
    batches = BroilerBatch.objects.all()
    if farm_ids is not None:
        batches = batches.filter(broiler_farm_id__in=farm_ids)

    open_rows = list(batches.filter(end_date__isnull=True, is_closed=False)
                     .order_by("broiler_farm_id", "-start_date", "-id")
                     .values("id", "broiler_farm_id", "batch_name", "start_date"))
    batch_ids = [row["id"] for row in open_rows]

    chick_ids = list(chick_items().values_list("id", flat=True))
    placed = _sum_by(
        StockTransfer.objects.filter(to_batch_id__in=batch_ids, item_id__in=chick_ids)
        .values("to_batch_id").annotate(qty=Sum("quantity"), first_date=Min("date")),
        "to_batch_id", "qty", "first_date")
    losses = _sum_by(
        DailyEntry.objects.filter(batch_id__in=batch_ids)
        .values("batch_id").annotate(m=Sum("mortality"), c=Sum("culls")),
        "batch_id", "m", "c")
    sold = _sum_by(
        BirdSale.objects.filter(batch_id__in=batch_ids)
        .values("batch_id").annotate(b=Sum("birds")),
        "batch_id", "b")

    overview = {}
    for row in open_rows:
        farm_id, batch_id = row["broiler_farm_id"], row["id"]
        counts, loss, sale = placed.get(batch_id, {}), losses.get(batch_id, {}), sold.get(batch_id, {})
        # start_date is not always filled — a batch created from a placement
        # can leave it blank — so the earliest chick transfer stands in, which
        # is what _placement_date does for the flock screens.
        placed_on = row["start_date"] or counts.get("first_date")
        live = (int(counts.get("qty") or 0) - int(loss.get("m") or 0)
                - int(loss.get("c") or 0) - int(sale.get("b") or 0))
        entry = overview.setdefault(farm_id, {
            "occupied": True, "batch_id": batch_id, "batch_name": row["batch_name"],
            "placed_on": placed_on, "age_days": None, "placed": 0, "live": 0,
            "open_batches": 0, "vacant_since": None,
        })
        entry["open_batches"] += 1
        entry["placed"] += int(counts.get("qty") or 0)
        entry["live"] += max(live, 0)
        # The newest batch names the farm; open_rows is ordered newest first.
        if placed_on and (entry["placed_on"] is None or placed_on > entry["placed_on"]):
            entry["placed_on"] = placed_on
    for entry in overview.values():
        if entry["placed_on"]:
            entry["age_days"] = (today - entry["placed_on"]).days
            entry["placed_on"] = entry["placed_on"].isoformat()

    # Farms with nothing open: when did the last flock leave?
    last_out = {}
    for row in batches.exclude(broiler_farm_id__in=overview).values(
            "broiler_farm_id", "end_date", "closed_on"):
        left = row["closed_on"] or row["end_date"]
        if left and (row["broiler_farm_id"] not in last_out or left > last_out[row["broiler_farm_id"]]):
            last_out[row["broiler_farm_id"]] = left
    for farm_id, left in last_out.items():
        overview[farm_id] = {
            "occupied": False, "batch_id": None, "batch_name": None, "placed_on": None,
            "age_days": None, "placed": 0, "live": 0, "open_batches": 0,
            "vacant_since": left.isoformat(),
        }
    return overview


def shed_totals(farm_ids=None):
    """{farm_id: {"shed_count": n, "shed_capacity": birds}}.

    Counted in its own query rather than annotated onto the farm list: the list
    already joins several tables, and a second join would multiply the rows a
    SUM sees.
    """
    sheds = BroilerFarmShed.objects.all()
    if farm_ids is not None:
        sheds = sheds.filter(farm_id__in=farm_ids)
    return {row["farm_id"]: {"shed_count": row["n"], "shed_capacity": int(row["cap"] or 0)}
            for row in sheds.values("farm_id").annotate(n=Count("id"), cap=Sum("capacity"))}


def utilisation(live, capacity):
    """Live birds as a percentage of what the farm holds, or None.

    None rather than 0 when capacity is missing: "we don't know" and "empty"
    are different answers, and a farm with no capacity recorded would otherwise
    read as 0% used and sort alongside genuinely empty farms.
    """
    if not capacity:
        return None
    return round(live * 100.0 / capacity, 1)


def farm_flags(farm, occupancy, sheds):
    """The warnings a farm row shows: capacity that disagrees with its sheds,
    an agreement running out, no location pin.

    Returned as plain strings so the list, the phone card and any export all
    say the same thing.
    """
    flags = []
    shed_capacity = sheds.get("shed_capacity") or 0
    capacity = farm.get("farm_capacity") or 0
    if shed_capacity and capacity and shed_capacity != capacity:
        flags.append(f"Sheds hold {shed_capacity:,} but the farm is set to {capacity:,}")
    if occupancy.get("live") and capacity and occupancy["live"] > capacity:
        flags.append("More birds placed than the farm holds")
    return flags


# What a farmer needs before money can move. Ordered the way the form asks for
# them, so the missing list reads in the order someone would fill them in.
PAYABLE_FIELDS = [
    ("farmer_group_id", "Farmer group"),
    ("acc_no", "Account number"),
    ("ifsc_code", "IFSC code"),
    ("account_holder_name", "Account holder"),
]
CONTACT_FIELDS = [("mobile_no", "Mobile")]
KYC_FIELDS = [("pan_no", "PAN")]


def farmer_gaps(farmer):
    """What this farmer is missing, as {"payable": [...], "other": [...]}.

    A farmer with no bank account and no group cannot be settled or paid, but
    nothing says so until settlement day — by which time the farmer is not
    reachable for a cancelled cheque. Naming the gap on the list is the whole
    point, so the labels are the ones the form uses.
    """
    payable = [label for field, label in PAYABLE_FIELDS if not farmer.get(field)]
    other = [label for field, label in CONTACT_FIELDS + KYC_FIELDS if not farmer.get(field)]
    return {"payable": payable, "other": other}
