"""Transfer Charges: allocation math, posting, and the read helpers the Add
Transfer Charges screen needs.

Follows the same shape as ``account.services.petty_expense`` — an
operational screen whose posting hands off to ``account.services.journal``
so a Transfer Charge is a voucher like any other and needs nothing of its
own in the ledger, trial balance or cost-centre report.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from account.models import CompanyProfile, Voucher
from account.services import journal

ZERO = Decimal('0')
TWOPLACES = Decimal('0.01')


class TransferChargeError(Exception):
    """Something that must stop a save/post, said in words a user can act on."""


def company():
    profile = CompanyProfile.objects.filter(pk=1).first()
    if profile is None:
        raise TransferChargeError("No company profile; the chart of accounts has no owner.")
    return profile


def _round2(value):
    return Decimal(value).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------
# Destination farms — what a trip's linked Stock Transfer rows resolve to.
# --------------------------------------------------------------------------

def destination_farms(stock_transfers):
    """One row per distinct destination farm among the given Stock Transfer
    rows, with the quantity/stock-value basis an allocation can weigh by.

    `stock_transfers` is any iterable/queryset of StockTransfer rows (already
    filtered to the ones this Transfer Charge is costing). Farm-less rows
    (warehouse-to-warehouse) are skipped — a charge can only be allocated to
    a destination that is a farm.
    """
    by_farm = {}
    order = []
    for row in stock_transfers:
        if row.to_location_type != 'farm' or not row.to_farm_id:
            continue
        farm = row.to_farm
        if farm.id not in by_farm:
            by_farm[farm.id] = {
                'farm_id': farm.id, 'farm_name': str(farm),
                'quantity': ZERO, 'stock_value': ZERO,
            }
            order.append(farm.id)
        qty = row.quantity or ZERO
        rate = row.rate or ZERO
        by_farm[farm.id]['quantity'] += qty
        by_farm[farm.id]['stock_value'] += (qty * rate)
    return [by_farm[fid] for fid in order]


def transfer_summary(stock_transfers):
    """The read-only summary cards: farms, items, quantity, stock value."""
    rows = list(stock_transfers)
    farms = destination_farms(rows)
    item_ids = {r.item_id for r in rows if r.item_id}
    total_qty = sum((r.quantity or ZERO) for r in rows) or ZERO
    total_value = sum((r.quantity or ZERO) * (r.rate or ZERO) for r in rows) or ZERO
    return {
        'farm_count': len(farms),
        'item_count': len(item_ids),
        'total_quantity': total_qty,
        'total_stock_value': total_value,
        'farms': farms,
    }


# --------------------------------------------------------------------------
# Allocation — split one Common charge across destination farms, or total up
# a Farm-wise one. No rounding loss: the last farm in `farms` absorbs
# whatever the rounded shares before it don't account for.
# --------------------------------------------------------------------------

def allocate_equal(farms, total_amount):
    return _spread(farms, total_amount, lambda f, total_weight: Decimal(1))


def allocate_by_quantity(farms, total_amount):
    return _spread(farms, total_amount, lambda f, total_weight: f['quantity'])


def allocate_by_stock_value(farms, total_amount):
    return _spread(farms, total_amount, lambda f, total_weight: f['stock_value'])


def allocate_by_distance(farms, total_amount):
    return _spread(farms, total_amount, lambda f, total_weight: f.get('distance') or ZERO)


def _spread(farms, total_amount, weight_of):
    """Shared engine for the weighted allocation methods. `weight_of` reads
    the weight off one farm dict; equal weighting is just a constant weight.
    Falls back to equal split when every weight is zero (e.g. By Quantity
    chosen before any quantity is known) rather than dividing by zero."""
    total_amount = Decimal(total_amount or 0)
    farms = list(farms)
    n = len(farms)
    if n == 0:
        return []
    weights = [weight_of(f, None) for f in farms]
    total_weight = sum(weights) or ZERO
    if total_weight <= 0:
        weights = [Decimal(1) for _ in farms]
        total_weight = Decimal(n)

    rows = []
    running = ZERO
    for i, (farm, weight) in enumerate(zip(farms, weights)):
        pct = (weight / total_weight) * Decimal(100)
        if i == n - 1:
            amount = total_amount - running
        else:
            amount = _round2(total_amount * weight / total_weight)
            running += amount
        rows.append({
            'farm_id': farm['farm_id'], 'farm_name': farm.get('farm_name', ''),
            'quantity_basis': farm.get('quantity', ZERO),
            'stock_value_basis': farm.get('stock_value', ZERO),
            'distance_basis': farm.get('distance'),
            'percentage': _round2(pct),
            'allocated_amount': amount,
        })
    return rows


ALLOCATORS = {
    'Equal': allocate_equal,
    'By Quantity': allocate_by_quantity,
    'By Stock Value': allocate_by_stock_value,
    'By Distance': allocate_by_distance,
}


def preview_allocation(line, farms):
    """What `allocate_*` would produce for a Common line right now, or the
    Farm-wise amounts already entered — the single function the Add page's
    live preview and the actual save both call, so they can never disagree."""
    if line.charge_scope == line.SCOPE_FARM_WISE:
        rows = []
        total = line.line_total
        for alloc in line.allocations.all():
            rows.append({
                'farm_id': alloc.destination_farm_id,
                'farm_name': str(alloc.destination_farm),
                'quantity_basis': alloc.quantity_basis, 'stock_value_basis': alloc.stock_value_basis,
                'distance_basis': alloc.distance_basis,
                'percentage': (_round2(alloc.allocated_amount / total * 100) if total else ZERO),
                'allocated_amount': alloc.allocated_amount,
            })
        return rows
    if line.allocation_method == 'Manual':
        return [{
            'farm_id': a.destination_farm_id, 'farm_name': str(a.destination_farm),
            'quantity_basis': a.quantity_basis, 'stock_value_basis': a.stock_value_basis,
            'distance_basis': a.distance_basis, 'percentage': a.percentage,
            'allocated_amount': a.allocated_amount,
        } for a in line.allocations.all()]
    allocator = ALLOCATORS.get(line.allocation_method, allocate_equal)
    return allocator(farms, line.total_amount)


# --------------------------------------------------------------------------
# Save — recompute every line's allocation rows from its current farms/method.
# --------------------------------------------------------------------------

@transaction.atomic
def recompute_allocations(header):
    """Rebuild every Common line's TransferChargeAllocation rows from its
    allocation method; leaves Farm-wise lines' rows untouched (those are
    entered directly, not derived). Call after the header's linked
    Stock Transfers or any line's method/amount changes."""
    from inventory.models import TransferChargeAllocation

    farms = destination_farms(header.stock_transfers.all())
    for line in header.lines.all():
        if line.charge_scope == line.SCOPE_FARM_WISE:
            continue
        rows = preview_allocation(line, farms)
        TransferChargeAllocation.objects.filter(line=line).exclude(
            destination_farm_id__in=[r['farm_id'] for r in rows]).delete()
        for row in rows:
            TransferChargeAllocation.objects.update_or_create(
                line=line, destination_farm_id=row['farm_id'],
                defaults={
                    'quantity_basis': row['quantity_basis'], 'stock_value_basis': row['stock_value_basis'],
                    'distance_basis': row['distance_basis'], 'percentage': row['percentage'],
                    'allocated_amount': row['allocated_amount'],
                })
    header.recalculate()
    header.save(update_fields=['total_transport', 'total_loading', 'total_unloading',
                               'total_other', 'total_charges', 'updated_at'])


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def validate(header):
    problems = []
    if not header.stock_transfers.exists():
        problems.append("Select a Stock Transfer before saving.")
    lines = list(header.lines.all())
    if not lines:
        problems.append("Add at least one charge line.")
    for line in lines:
        if (line.total_amount or ZERO) < 0:
            problems.append(f"{line.charge_type}: amount cannot be negative.")
        if line.charge_scope == line.SCOPE_COMMON:
            allocated = sum((a.allocated_amount or ZERO) for a in line.allocations.all())
            if allocated != (line.total_amount or ZERO):
                problems.append(
                    f"{line.charge_type}: allocated total ({allocated}) does not equal "
                    f"the charge amount ({line.total_amount}).")
        else:
            for alloc in line.allocations.all():
                if alloc.allocated_amount is None or alloc.allocated_amount < 0:
                    problems.append(
                        f"{line.charge_type}: {alloc.destination_farm} needs a valid amount.")
        ledger = line.charge_type.ledger_for(header.treatment)
        if ledger is None:
            problems.append("Accounting mapping is not configured for this charge type.")
    return problems


# --------------------------------------------------------------------------
# Posting — one debit per (charge type x farm) allocation, to the ledger the
# charge type is mapped to for this header's treatment; one credit to the
# account the money left. Mirrors account.services.petty_expense.post.
# --------------------------------------------------------------------------

def compose_narration(header):
    transfers = list(header.stock_transfers.select_related('from_warehouse', 'from_farm').all())
    from_names = sorted({str(t.from_location) for t in transfers if t.from_location})
    farms = destination_farms(transfers)
    to_names = [f['farm_name'] for f in farms]
    from_text = from_names[0] if from_names else "source"
    if len(to_names) <= 1:
        to_text = to_names[0] if to_names else "destination"
    else:
        to_text = ", ".join(to_names[:-1]) + " and " + to_names[-1]
    return f"Transfer charges for {header.dc_no} from {from_text} to {to_text}."


def _allocation_rows(header):
    from inventory.models import TransferChargeAllocation
    return TransferChargeAllocation.objects.filter(line__header=header).select_related(
        'line__charge_type', 'destination_farm')


@transaction.atomic
def post(header, user=None):
    from account.services.bank_cash import ledger_for_bank_cash

    if header.status == header.STATUS_POSTED:
        raise TransferChargeError(f"{header.charge_no} is already posted.")
    if header.status == header.STATUS_CANCELLED:
        raise TransferChargeError(f"{header.charge_no} has been cancelled and cannot be posted.")

    recompute_allocations(header)
    problems = validate(header)
    if problems:
        raise TransferChargeError(problems[0] if len(problems) == 1 else "  ".join(problems))

    profile = header.company or company()
    centre = header.cost_centre_id or None

    rows = []
    for alloc in _allocation_rows(header):
        ledger = alloc.line.charge_type.ledger_for(header.treatment)
        amount = alloc.allocated_amount or ZERO
        if not amount:
            continue
        rows.append({
            'account': ledger.pk, 'cost_center': centre, 'debit': amount, 'credit': 0,
            'narration': f"{alloc.line.charge_type}: {alloc.destination_farm}"[:255],
        })

    if not rows:
        raise TransferChargeError("Nothing to post — every charge line is zero.")

    if header.paid_from_id:
        credit_ledger = ledger_for_bank_cash(header.paid_from)
    else:
        raise TransferChargeError("Select the Cash/Bank account the charges were paid from.")

    rows.append({
        'account': credit_ledger.pk, 'cost_center': centre, 'debit': 0,
        'credit': sum((r['debit'] for r in rows), ZERO), 'narration': header.dc_no[:255],
    })

    narration = header.narration or compose_narration(header)

    try:
        voucher = journal.create_voucher(
            profile, header.charge_date, rows,
            user=user, voucher_type='Payment', manual=False, system_generated=True,
            reference=header.dc_no or header.charge_no,
            narration=narration, post=True,
        )
    except DjangoValidationError as exc:
        raise TransferChargeError("  ".join(exc.messages)) from exc

    header.voucher = voucher
    header.status = header.STATUS_POSTED
    header.posted_by = user
    from django.utils import timezone
    header.posted_at = timezone.now()
    header.save(update_fields=['voucher', 'status', 'posted_by', 'posted_at', 'updated_at'])
    return voucher


@transaction.atomic
def cancel(header, user=None, reason=""):
    if header.status == header.STATUS_CANCELLED:
        raise TransferChargeError(f"{header.charge_no} is already cancelled.")

    if header.voucher_id and header.voucher.status == 'Posted':
        journal.cancel_voucher(header.voucher, user=user,
                               reason=reason or "Transfer charge cancelled")

    header.status = header.STATUS_CANCELLED
    header.cancelled_by = user
    from django.utils import timezone
    header.cancelled_at = timezone.now()
    header.cancel_reason = (reason or "")[:255]
    header.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancel_reason', 'updated_at'])
    return header


def vouchers_for(header):
    return Voucher.objects.filter(transfer_charge_source=header)
