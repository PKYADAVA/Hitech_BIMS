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
                     FarmerGCPaymentAttachment, FarmerGCPaymentLine, GrowingChargeSettlement)
from .services import gc_posting
from Hitech_BIMS.entry_dates import date_from_query


def _line_dict(line):
    return {
        "id": line.id,
        # The number this row already carries, so the grid shows the real one
        # rather than a preview of the next.
        "payment_no": line.payment.payment_no,
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
        # The narration belongs to the payment, and a payment now holds one
        # line, so the row carries its own payment's sentence back to the
        # grid. An auto-written one is left out: showing it in the box would
        # turn it into a hand-typed narration on the next save, and those are
        # never rewritten when the amounts behind them change.
        "narration": ("" if line.payment.narration == line.payment.compose_narration()
                      else line.payment.narration),
    }


def _context(user, payment=None):
    from account.services.bank_cash import (active_payment_modes,
                                            bank_cash_accounts,
                                            payment_mode_map)
    return {
        "payment": payment,
        # Always supplied, not only when adding: editing can add rows too, and
        # each of those becomes a payment of its own needing a number.
        "next_payment_no": FarmerGCPayment._next_payment_no(),
        "farms": farms_for(user, BroilerFarm.objects.select_related("farmer")
                           .order_by("farm_name")),
        # Only real cash and bank ledgers. Money cannot leave through a sales
        # account, and offering every ledger invites exactly that.
        "accounts": bank_cash_accounts(),
        "pay_types": FarmerGCPaymentLine.PAY_TYPE_CHOICES,
        # From the Payment Mode master, as every other payment and receipt
        # form reads it. This one kept the five names hardcoded on the
        # model, so a mode the office added — "Paytm Business Wallet" —
        # appeared on those forms and not on this one.
        "payment_modes": active_payment_modes("payment"),
        "payment_mode_map_json": json.dumps(payment_mode_map("payment")),
        "today": timezone.localdate().isoformat(),
        "existing_lines_json": json.dumps(
            [_line_dict(r) for r in payment.lines.select_related(
                "farm__farmer", "batch", "pay_account",
                "payment")] if payment else []),
    }


@login_required(login_url="login")
def farmer_gc_payment(request):
    """The register: a date range, and the vouchers written in it."""
    from broiler.models import Branch

    return render(request, "farmer_gc_payment_list.html", {
        # Only the branches the user may see, and only those with a farm:
        # a branch that can never match anything reads as a broken filter.
        "branches": scope_any(request.user, Branch.objects.all(), branches="id")
        .filter(broiler_farms__isnull=False).distinct().order_by("branch_name"),
        "years": range(timezone.localdate().year, timezone.localdate().year - 6, -1),
    })


@login_required(login_url="login")
def farmer_gc_payment_api(request):
    """JSON rows for the register's DataTable."""
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    month = (request.GET.get("month") or "").strip()
    year = (request.GET.get("year") or "").strip()
    branch = (request.GET.get("branch") or "").strip()

    qs = scope_any(request.user, FarmerGCPayment.objects.all(),
                   farms="lines__farm_id").prefetch_related(
        "lines__farm__farmer", "lines__pay_account", "attachments")
    if from_date:
        qs = qs.filter(date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(date__lte=date_from_query(to_date))
    # Month and year narrow within whatever the dates already allow, so
    # picking a month does not silently widen a chosen range.
    if year.isdigit():
        qs = qs.filter(date__year=int(year))
    if month.isdigit():
        qs = qs.filter(date__month=int(month))
    if branch.isdigit():
        # Through the line's farm: a payment has no branch of its own. distinct
        # because the join can repeat a payment that has several lines.
        qs = qs.filter(lines__farm__branch_id=int(branch)).distinct()

    return JsonResponse({"data": [{
        "id": p.id,
        "date": p.date.strftime("%d-%m-%Y"),
        "trnum": p.payment_no,
        "farm": p.farm_summary,
        "pay_type": p.pay_type_summary,
        "mode": p.mode_summary,
        "method": p.method_summary,
        "reference": p.reference_summary,
        "amount": f"{p.total_amount:.2f}",
        "attachments": [{"id": a.id, "url": a.file.url,
                        "name": a.file.name.rsplit("/", 1)[-1], "caption": a.caption}
                       for a in p.attachments.all()],
    } for p in qs]})


@login_required(login_url="login")
def farmer_gc_payment_attachments(request, id):
    """List (GET) / upload (POST) / delete (DELETE ?attachment=<id>) proof
    filed against a Farmer GC Payment voucher."""
    from user.access import user_can

    payment = get_object_or_404(FarmerGCPayment, id=id)

    if request.method == "GET":
        return JsonResponse([{
            "id": a.id, "url": a.file.url, "name": a.file.name.rsplit("/", 1)[-1],
            "caption": a.caption,
            "uploaded_by": a.uploaded_by.username if a.uploaded_by_id else "",
            "uploaded_at": timezone.localtime(a.uploaded_at).strftime("%d-%b-%Y %H:%M"),
        } for a in payment.attachments.select_related("uploaded_by")], safe=False)

    if request.method == "POST":
        if not user_can(request.user, "farmer_gc_payment", "add"):
            return JsonResponse({"error": "Not permitted."}, status=403)
        uploads = request.FILES.getlist("files")
        if not uploads:
            return JsonResponse({"error": "Choose at least one file."}, status=400)
        caption = (request.POST.get("caption") or "").strip()
        created = [FarmerGCPaymentAttachment.objects.create(
            payment=payment, file=upload, caption=caption, uploaded_by=request.user)
            for upload in uploads]
        return JsonResponse({"message": "%d file(s) uploaded." % len(created)}, status=201)

    if request.method == "DELETE":
        if not user_can(request.user, "farmer_gc_payment", "edit"):
            return JsonResponse({"error": "Not permitted."}, status=403)
        attachment_id = request.GET.get("attachment")
        attachment = get_object_or_404(payment.attachments, id=attachment_id)
        attachment.file.delete(save=False)
        attachment.delete()
        return JsonResponse({"message": "Attachment deleted."})

    return JsonResponse({"error": "Unsupported method."}, status=405)


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


def _rows_from(request):
    """The entry grid's rows, with the unusable ones dropped."""
    try:
        rows = json.loads(request.POST.get("lines_json") or "[]")
    except json.JSONDecodeError:
        rows = []
    return [r for r in rows if r.get("farm") and r.get("pay_account")]


def _apply_line(payment, row):
    """Replace this payment's single line with ``row``."""
    payment.lines.all().delete()
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


def _finish(payment, request):
    """Narration and posting, once a payment has its line."""
    # Left empty by the form, the voucher still needs a sentence an
    # accountant can read. Typed by hand, it is never overwritten.
    if not payment.narration:
        payment.narration = payment.compose_narration()
        payment.save(update_fields=["narration"])
    # Inside the same transaction as the save, so a posting failure takes
    # the voucher down with it rather than leaving money recorded as paid
    # with nothing on the books to say where it went.
    gc_posting.post_payment_if_enabled(payment, user=request.user)


def _save(request, payment):
    """Save the entry grid.

    One payment per row, each with its own payment number, rather than one
    voucher carrying every row: each row pays a different farm, and a farmer
    asking which payment settled their charges has to be able to be told a
    number that means only theirs. The lines table is kept -- the posting
    service and the register both read through it -- but a payment now holds
    exactly one line.

    Adding returns the payments created; editing keeps the record the user
    opened and applies the first row to it, so a payment number already
    quoted to a farmer does not change underneath them. Extra rows added
    while editing become payments of their own.
    """
    date = request.POST.get("date") or timezone.localdate()
    # Kept as a fallback for anything still posting one narration for the
    # whole form; the grid now carries one per row.
    fallback = (request.POST.get("narration") or "").strip()
    rows = _rows_from(request)
    if not rows:
        raise ValidationError("Add at least one payment line.")

    saved = []
    with transaction.atomic():
        for index, row in enumerate(rows):
            # The record being edited takes the first row; everything else is
            # new, including every row when adding.
            current = payment if (index == 0 and payment.pk) else FarmerGCPayment()
            current.date = date
            current.narration = (row.get("narration") or "").strip() or fallback
            current.full_clean(exclude=["payment_no"])
            current.save()
            _apply_line(current, row)
            _finish(current, request)
            saved.append(current)
    return saved


@login_required(login_url="login")
def farmer_gc_payment_add(request):
    if request.method == "POST":
        payment = FarmerGCPayment()
        try:
            saved = _save(request, payment)
            # Named rather than counted: the numbers are the point of saving
            # each row separately, so the user leaves knowing what they are.
            if len(saved) == 1:
                messages.success(
                    request, f"Farmer payment {saved[0].payment_no} added.")
            else:
                messages.success(
                    request,
                    "%d farmer payments added: %s."
                    % (len(saved), ", ".join(p.payment_no for p in saved)))
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
            saved = _save(request, payment)
            extra = [p for p in saved if p.pk != payment.pk]
            if extra:
                messages.success(
                    request,
                    "Farmer payment %s updated; %s added."
                    % (payment.payment_no, ", ".join(p.payment_no for p in extra)))
            else:
                messages.success(
                    request, f"Farmer payment {payment.payment_no} updated.")
            return redirect("farmer_gc_payment")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages)
                           if hasattr(e, "messages") else str(e))
    return render(request, "farmer_gc_payment_form.html",
                  _context(request.user, payment))


@login_required(login_url="login")
@require_POST
@transaction.atomic
def farmer_gc_payment_delete(request, id):
    payment = get_object_or_404(FarmerGCPayment, id=id)
    # Unpost before deleting: the voucher is found through a link to this
    # record, so once it is gone there is nothing left to find it by.
    gc_posting.reverse_if_posted(payment, user=request.user,
                                 reason="Payment deleted")
    payment.delete()
    return JsonResponse({"success": True})
