"""Farmer GC Payment — Broiler > Farmer GC & Payment > GC Payment.

Paying a farmer what the growing-charge settlement said they were owed.

A header per voucher with a line per farmer, the same shape as
``purchase.SupplierPayment`` and for the same reason: a day's payments are
written up together, and the register wants one row per voucher rather than one
per farmer. The list's Farm / Farmer / Mode / Method columns are summaries over
the lines and read "Multiple" when a voucher covers more than one.

Its own module rather than more of ``views.py``, which is already 8,000 lines —
the route planner went the same way.
"""
import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from user.services.scoping import farms_for, scope_any

from .models import (BroilerBatch, BroilerFarm, FarmerGCPayment,
                     FarmerGCPaymentLine, GrowingChargeSettlement)


def _line_dict(line):
    return {
        "id": line.id,
        "farm": line.farm_id,
        "farm_name": line.farm.farm_name,
        "batch": line.batch_id,
        "batch_name": line.batch.batch_name if line.batch_id else "",
        "pay_type": line.pay_type,
        "mode": line.mode,
        "pay_account": line.pay_account_id,
        "gc_amount": str(line.gc_amount),
        "amount": str(line.amount),
        "bank_charges": str(line.bank_charges),
        "reference_no": line.reference_no,
        "remarks": line.remarks,
    }


def _context(user, payment=None):
    from account.services.bank_cash import bank_cash_accounts
    return {
        "payment": payment,
        "next_payment_no": FarmerGCPayment._next_payment_no() if not payment else None,
        "farms": farms_for(user, BroilerFarm.objects.select_related("farmer")
                           .order_by("farm_name")),
        # Only real cash and bank ledgers. Money cannot leave through a sales
        # account, and offering every ledger invites exactly that.
        "accounts": bank_cash_accounts(),
        "pay_types": FarmerGCPaymentLine.PAY_TYPE_CHOICES,
        "mode_choices": FarmerGCPaymentLine.MODE_CHOICES,
        "today": timezone.localdate().isoformat(),
        "existing_lines_json": json.dumps(
            [_line_dict(r) for r in payment.lines.select_related(
                "farm", "batch", "pay_account")] if payment else []),
    }


@login_required(login_url="login")
def farmer_gc_payment(request):
    """The register: a date range, and the vouchers written in it."""
    return render(request, "farmer_gc_payment_list.html")


@login_required(login_url="login")
def farmer_gc_payment_api(request):
    """JSON rows for the register's DataTable."""
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()

    qs = scope_any(request.user, FarmerGCPayment.objects.all(),
                   farms="lines__farm_id").prefetch_related(
        "lines__farm__farmer", "lines__pay_account")
    if from_date:
        qs = qs.filter(date__gte=from_date)
    if to_date:
        qs = qs.filter(date__lte=to_date)

    return JsonResponse({"data": [{
        "id": p.id,
        "date": p.date.strftime("%d-%m-%Y"),
        "trnum": p.payment_no,
        "farm": p.farm_summary,
        "farmer": p.farmer_summary,
        "mode": p.mode_summary,
        "method": p.method_summary,
        "amount": f"{p.total_amount:.2f}",
    } for p in qs]})


@login_required(login_url="login")
def farmer_gc_payment_batches(request):
    """Batches for a farm, for the Batch dropdown.

    Every batch, not only the open ones: a growing charge is settled as the
    batch closes, so by the time there is anything to pay for it the batch is
    already shut.
    """
    farm_id = (request.GET.get("farm") or "").strip()
    if not farm_id.isdigit():
        return JsonResponse([], safe=False)
    batches = (BroilerBatch.objects.filter(broiler_farm_id=farm_id)
               .order_by("-start_date", "-id"))
    return JsonResponse([{"id": b.id, "batch_name": b.batch_name} for b in batches],
                        safe=False)


@login_required(login_url="login")
def farmer_gc_payment_gc_amount(request):
    """What the settlement says this batch owes the farmer, and what is left.

    Shown beside the amount being entered so nobody has to leave the form to
    find it. Payments already made against the same batch are netted off: the
    question being asked is how much is still outstanding, not what the charge
    originally was. Editing a voucher excludes its own lines, or its previous
    amount would count against it.
    """
    batch_id = (request.GET.get("batch") or "").strip()
    exclude = (request.GET.get("exclude") or "").strip()
    if not batch_id.isdigit():
        return JsonResponse({"gc_amount": "0.00", "paid": "0.00",
                             "outstanding": "0.00", "settled": False})

    settlement = GrowingChargeSettlement.objects.filter(batch_id=batch_id).first()
    gc_amount = settlement.farmer_payable if settlement else Decimal("0")

    paid = FarmerGCPaymentLine.objects.filter(batch_id=batch_id)
    if exclude.isdigit():
        paid = paid.exclude(payment_id=exclude)
    already = paid.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    return JsonResponse({
        "gc_amount": f"{gc_amount:.2f}",
        "paid": f"{already:.2f}",
        "outstanding": f"{(gc_amount - already):.2f}",
        "settled": bool(settlement),
    })


def _save_lines(payment, request):
    try:
        rows = json.loads(request.POST.get("lines_json") or "[]")
    except json.JSONDecodeError:
        rows = []
    payment.lines.all().delete()
    for row in rows:
        if not row.get("farm") or not row.get("pay_account"):
            continue
        FarmerGCPaymentLine.objects.create(
            payment=payment,
            farm_id=row["farm"],
            batch_id=row.get("batch") or None,
            pay_type=row.get("pay_type") or "GC Pay",
            mode=row.get("mode") or "Cash",
            pay_account_id=row["pay_account"],
            gc_amount=Decimal(str(row.get("gc_amount") or 0)),
            amount=Decimal(str(row.get("amount") or 0)),
            bank_charges=Decimal(str(row.get("bank_charges") or 0)),
            reference_no=row.get("reference_no") or "",
            remarks=row.get("remarks") or "",
        )


def _save(request, payment):
    """Shared by add and edit: the two differ only in which record they hold."""
    payment.date = request.POST.get("date") or timezone.localdate()
    payment.narration = (request.POST.get("narration") or "").strip()
    payment.full_clean(exclude=["payment_no"])
    with transaction.atomic():
        payment.save()
        _save_lines(payment, request)
        if not payment.lines.exists():
            raise ValidationError("Add at least one payment line.")
        # Left empty by the form, the voucher still needs a sentence an
        # accountant can read. Typed by hand, it is never overwritten.
        if not payment.narration:
            payment.narration = payment.compose_narration()
            payment.save(update_fields=["narration"])


@login_required(login_url="login")
def farmer_gc_payment_add(request):
    if request.method == "POST":
        payment = FarmerGCPayment()
        try:
            _save(request, payment)
            messages.success(request, "Farmer payment added successfully.")
            return redirect("farmer_gc_payment")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages)
                           if hasattr(e, "messages") else str(e))
    return render(request, "farmer_gc_payment_form.html", _context(request.user))


@login_required(login_url="login")
def farmer_gc_payment_edit(request, id):
    payment = get_object_or_404(FarmerGCPayment, id=id)
    if request.method == "POST":
        try:
            _save(request, payment)
            messages.success(request, "Farmer payment updated successfully.")
            return redirect("farmer_gc_payment")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages)
                           if hasattr(e, "messages") else str(e))
    return render(request, "farmer_gc_payment_form.html",
                  _context(request.user, payment))


@login_required(login_url="login")
@require_POST
def farmer_gc_payment_delete(request, id):
    get_object_or_404(FarmerGCPayment, id=id).delete()
    return JsonResponse({"success": True})
