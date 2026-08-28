"""Supplier List and Customer List — the party masters as a report.

Not balance reports. These answer "who do we deal with, and is their record
complete" rather than "what do they owe" — which is why they carry the whole
master rather than a chosen handful of columns.

Every field on the model is a column, read from the model itself rather than
listed here. A hand-written list would be wrong the first time someone adds a
field to Supplier and forgets this file, and "all the columns" would quietly
become "the columns somebody typed out in 2026".

One module for both, because they are the same report over two tables. Keeping
them apart would mean every future change made twice; this codebase already has
three near-identical ledger reports that drifted exactly that way.
"""
from decimal import Decimal

from django.db import models
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

#: Nothing a person reading a party list needs. The primary key is plumbing,
#: and the two upload fields are covered by a Yes/No rather than a path nobody
#: can click from a printed page.
SKIP_FIELDS = {"id"}

#: Columns whose numbers are worth a total. Anything else numeric on these
#: masters — a credit term in days, a count of months — sums to nonsense.
TOTALLED = {"credit_limit", "opening_balance"}


#: Titlecasing a field name turns GSTIN into "Gstin" and IFSC into "Ifsc code",
#: which reads as a typo on a document people print and hand to an auditor.
#: Only the acronyms need saying; everything else is fine derived.
LABEL_OVERRIDES = {
    "gstin": "GSTIN",
    "pan": "PAN",
    "pan_tin": "PAN / TIN",
    "ifsc_code": "IFSC Code",
    "account_no": "A/c No.",
    "aadhar": "Aadhaar",
    "mobile_2": "Mobile 2",
    "to_pay_to_receive": "To Pay / To Receive",
    "as_on_date": "As On",
    "credit_term": "Credit Days",
    "credit_period": "Credit Period",
}


def _label(field):
    if field.name in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[field.name]
    text = str(field.verbose_name or field.name).strip()
    return text[:1].upper() + text[1:] if text else field.name


def _format(party, field):
    """One cell, as a person would want to read it."""
    value = getattr(party, field.name, None)

    if isinstance(field, models.FileField):
        # A storage path is unusable on a printed page and misleading on screen.
        return "Yes" if value else ""
    if value in (None, ""):
        return ""
    if isinstance(field, models.ForeignKey):
        return str(value)
    if isinstance(field, models.BooleanField):
        return "Yes" if value else "No"
    if isinstance(field, models.DecimalField):
        return f"{Decimal(str(value)):,.2f}"
    if isinstance(field, models.DateTimeField):
        return timezone.localtime(value).strftime("%d-%m-%Y %H:%M")
    if isinstance(field, models.DateField):
        return value.strftime("%d-%m-%Y")
    return str(value)


def _columns(model):
    out = []
    for field in model._meta.fields:
        if field.name in SKIP_FIELDS:
            continue
        numeric = isinstance(field, (models.DecimalField, models.IntegerField,
                                     models.FloatField))
        out.append({
            "name": field.name,
            "label": _label(field),
            "numeric": numeric,
            "totalled": field.name in TOTALLED,
        })
    return out


def party_list_report(request, *, kind, model, queryset, group_label,
                      group_choices, group_field, title):
    """Render (or export) a party master listing.

    ``queryset`` arrives already scoped by the caller — suppliers and customers
    have their own scoping helpers, and choosing between them here would mean
    this module knowing which master it is looking at.
    """
    from django.db.models import Q

    from account.models import CompanyProfile

    group = (request.GET.get("group") or "").strip()
    q = (request.GET.get("q") or "").strip()
    gst = (request.GET.get("gst") or "").strip()
    export = (request.GET.get("export") or "").strip().lower()

    if group:
        queryset = queryset.filter(**{group_field: group})
    if gst == "with":
        queryset = queryset.exclude(gstin__isnull=True).exclude(gstin="")
    elif gst == "without":
        # A blank and a NULL both mean "no GSTIN". Catching only one would leave
        # the two halves not adding up to the count on the card above them.
        queryset = queryset.filter(Q(gstin__isnull=True) | Q(gstin=""))
    if q:
        queryset = queryset.filter(
            Q(name__icontains=q) | Q(code__icontains=q)
            | Q(gstin__icontains=q) | Q(mobile__icontains=q))

    columns = _columns(model)
    rows, totals_by_column = [], {c["name"]: Decimal("0") for c in columns if c["totalled"]}
    with_gstin = 0

    for party in queryset:
        rows.append({"cells": [_format(party, model._meta.get_field(c["name"]))
                               for c in columns]})
        if getattr(party, "gstin", ""):
            with_gstin += 1
        for name in totals_by_column:
            totals_by_column[name] += Decimal(str(getattr(party, name, 0) or 0))

    totals = {
        "count": len(rows),
        "with_gstin": with_gstin,
        "credit_limit": totals_by_column.get("credit_limit", Decimal("0")),
        "opening": totals_by_column.get("opening_balance", Decimal("0")),
    }

    # Hung on the column itself so the footer row can simply read it, rather
    # than the template looking a value up by name mid-loop.
    for column in columns:
        if column["totalled"]:
            column["total"] = f"{totals_by_column[column['name']]:,.2f}"

    if export == "excel":
        return _excel(title, columns, rows, totals)

    return render(request, "party_list_report.html", {
        "kind": kind,
        "noun": kind,
        "title": title,
        "group_label": group_label,
        "groups": group_choices,
        "group": group,
        "q": q,
        "gst": gst,
        "columns": columns,
        "rows": rows,
        "totals": totals,
        "company": CompanyProfile.objects.filter(pk=1).first(),
        "today": timezone.localdate(),
    })


def _excel(title, columns, rows, totals):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]                      # Excel refuses a longer sheet name
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"{totals['count']} listed, {totals['with_gstin']} with GSTIN"])
    ws.append([])

    ws.append(["#"] + [c["label"] for c in columns])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for index, row in enumerate(rows, start=1):
        ws.append([index] + row["cells"])

    ws.append([])
    footer = [""] * (len(columns) + 1)
    footer[0] = "Total"
    for position, column in enumerate(columns, start=1):
        if column["totalled"]:
            footer[position] = column["total"]
    ws.append(footer)
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)

    ws.freeze_panes = "B5"                     # the header row and the number column
    ws.column_dimensions["A"].width = 5
    for position, column in enumerate(columns, start=1):
        letter = ws.cell(row=4, column=position + 1).column_letter
        ws.column_dimensions[letter].width = max(12, min(34, len(column["label"]) + 6))

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = (
        f'attachment; filename="{title.lower().replace(" ", "_")}.xlsx"')
    wb.save(response)
    return response
