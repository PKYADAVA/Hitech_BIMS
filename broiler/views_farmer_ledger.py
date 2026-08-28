"""Farmer Ledger — Broiler > Reports > Farmer Ledger.

A farmer's running account with the company. Two things move it:

  credit   a growing charge settled on one of their batches — what the
           settlement said we owe them
  debit    a GC payment made to them — what we have actually handed over

The closing balance is therefore what is still owed. It reads the same way the
Supplier Ledger does, so anyone who can read one can read the other.

Bank charges are deliberately not part of the farmer's side of it. They are
what the transfer cost us, not money the farmer received, and putting them here
would make the ledger disagree with what landed in their account.

Farmers have no opening balance field of their own, so the account starts at
zero and is built entirely from settlements and payments. If opening balances
are ever needed they belong on the Farmer master, not conjured here.
"""
from collections import OrderedDict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.utils.dateparse import parse_date

from user.services.scoping import farms_for

from .models import (BroilerFarm, Farmer, FarmerGCPaymentLine,
                     GrowingChargeSettlement)


def _num(value):
    return Decimal(str(value or 0))


def _visible_farmers(user):
    """Farmers reachable through a farm the user is allowed to see.

    There is no farmer scope of its own, and inventing one would let a branch
    user read the account of a farmer whose farms they cannot open.
    """
    farm_ids = farms_for(user, BroilerFarm.objects.all()).values("farmer_id")
    return Farmer.objects.filter(id__in=farm_ids).order_by("farmer_name")


def _ledger(user, farmer, fd, td):
    """Rows, month groups and totals for one farmer's account."""
    farms = farms_for(user, BroilerFarm.objects.filter(farmer=farmer))

    settlements = list(GrowingChargeSettlement.objects
                       .filter(farm__in=farms)
                       .select_related("batch", "farm")
                       .order_by("gc_date", "id"))
    payments = list(FarmerGCPaymentLine.objects
                    .filter(farm__in=farms)
                    .select_related("payment", "farm", "batch", "pay_account")
                    .order_by("payment__date", "id"))

    # Everything before the window is folded into one opening figure rather
    # than listed, which is what makes a date-ranged statement readable.
    opening = Decimal("0")
    for s in settlements:
        if fd and s.gc_date and s.gc_date < fd:
            opening += _num(s.farmer_payable)
    for p in payments:
        if fd and p.payment.date and p.payment.date < fd:
            opening -= _num(p.amount)

    events = []
    for s in settlements:
        if s.gc_date and ((fd and s.gc_date < fd) or (td and s.gc_date > td)):
            continue
        events.append((s.gc_date, 0, "GC", s))
    for p in payments:
        d = p.payment.date
        if d and ((fd and d < fd) or (td and d > td)):
            continue
        events.append((d, 1, "PAY", p))
    # A settlement and its payment on the same day read in that order: the
    # charge is raised before it is paid.
    events.sort(key=lambda e: (e[0] or parse_date("1900-01-01"), e[1]))

    groups = OrderedDict()

    def group_for(d):
        key = d.strftime("%B %Y") if d else "Undated"
        if key not in groups:
            groups[key] = {"label": key, "rows": [],
                           "debit": Decimal("0"), "credit": Decimal("0")}
        return groups[key]

    running = opening
    totals = {"debit": Decimal("0"), "credit": Decimal("0"),
              "settlements": 0, "payments": 0}

    for when, _order, kind, obj in events:
        grp = group_for(when)
        if kind == "GC":
            credit, debit = _num(obj.farmer_payable), Decimal("0")
            particulars = f"Growing charge — {obj.batch.batch_name}"
            voucher, farm = obj.settlement_code, obj.farm.farm_name
            detail = obj.scheme.schema_name if obj.scheme_id else ""
            totals["settlements"] += 1
        else:
            credit, debit = Decimal("0"), _num(obj.amount)
            particulars = f"{obj.pay_type} — {obj.mode}"
            voucher, farm = obj.payment.payment_no, obj.farm.farm_name
            detail = " · ".join(x for x in (
                obj.batch.batch_name if obj.batch_id else "",
                obj.pay_account.description if obj.pay_account_id else "",
                obj.reference_no) if x)
            totals["payments"] += 1

        running += credit - debit
        grp["rows"].append({
            "date": when, "particulars": particulars, "voucher": voucher,
            "farm": farm, "detail": detail,
            "debit": debit, "credit": credit, "balance": running,
        })
        grp["debit"] += debit
        grp["credit"] += credit
        totals["debit"] += debit
        totals["credit"] += credit

    return {
        "opening": opening,
        "groups": list(groups.values()),
        "totals": totals,
        "closing": running,
    }


@login_required(login_url="login")
def farmer_ledger_report(request):
    """Broiler > Reports > Farmer Ledger."""
    farmer_id = (request.GET.get("farmer") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()

    fd = parse_date(from_date) if from_date else None
    td = parse_date(to_date) if to_date else None

    # A querystring is not a permission: a farmer outside the user's scope
    # resolves to None rather than having their account printed.
    farmer = (_visible_farmers(request.user).filter(id=farmer_id).first()
              if farmer_id.isdigit() else None)

    data = _ledger(request.user, farmer, fd, td) if farmer else None

    if export == "excel" and data:
        return _excel(farmer, data, from_date, to_date)

    return render(request, "farmer_ledger_report.html", {
        "farmers": _visible_farmers(request.user),
        "farmer": farmer,
        "farmer_id": farmer.id if farmer else "",
        "from_date": from_date,
        "to_date": to_date,
        "data": data,
    })


def _excel(farmer, data, from_date, to_date):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Farmer Ledger"
    ws.append([f"Farmer Ledger — {farmer.farmer_name}"])
    ws.append([f"{from_date or 'beginning'} to {to_date or 'date'}"])
    ws.append([])
    ws.append(["Date", "Particulars", "Voucher", "Farm", "Detail",
               "Debit", "Credit", "Balance"])
    ws.append(["", "Opening balance", "", "", "", "", "", float(data["opening"])])
    for group in data["groups"]:
        for row in group["rows"]:
            ws.append([
                row["date"].strftime("%d-%m-%Y") if row["date"] else "",
                row["particulars"], row["voucher"], row["farm"], row["detail"],
                float(row["debit"]), float(row["credit"]), float(row["balance"]),
            ])
    ws.append(["", "Total", "", "", "",
               float(data["totals"]["debit"]), float(data["totals"]["credit"]),
               float(data["closing"])])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    name = farmer.farmer_name.replace(" ", "_")
    response["Content-Disposition"] = f'attachment; filename="farmer_ledger_{name}.xlsx"'
    wb.save(response)
    return response
