"""Account transaction write endpoints for the mobile API v1.

These deliberately **reuse the web module's own views verbatim**
(``account.petty_api``): each mobile view hands the JWT-authenticated user to
the function the web form calls, so every create, post, cancel and delete runs
the identical validation, cash-box check, narration and journal posting as the
web. No second, drift-prone copy of that logic lives here.

The petty expense register is one screen on the phone and two calls: the list
comes back with the figures above it (``rows`` and ``cards``) because they are
counted from the same queryset, and the entry screen asks once for everything
its pickers hold.

Mounted under ``/api/v1/account/petty-expenses/…`` by ``api/urls.py``.
"""
from __future__ import annotations

import json

from django.http import Http404 as DjangoHttp404
from django.urls import path
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import MatrixPermission
from api.viewsets import V1ViewMixin

from . import journal_api as journal_web
from . import petty_api as web

#: The matrix tabs these endpoints belong to. Set explicitly so the phone is
#: held to the same Web-Access rights as the browser, and narrowed again by
#: Mobile Access, without waiting for a model-to-tab mapping.
TAB = "petty_expense_list"
VOUCHER_TAB = "vouchers"


def _delegate(view, request, *args) -> Response:
    """Run a web view as the mobile user, then envelope what it answered.

    The web views read ``request.body`` and ``request.user``; they are handed
    the raw Django request with the authenticated user attached, so the body
    stream stays readable downstream. A 4xx ``{"error": ...}`` becomes a DRF
    ``ValidationError``, which is what the app shows against the form.
    """
    django_request = getattr(request, "_request", request)
    django_request.user = request.user
    try:
        resp = view(django_request, *args)
    except DjangoHttp404 as exc:
        raise NotFound(str(exc) or "Record not found.")

    payload = json.loads(resp.content or b"{}")
    if resp.status_code >= 400:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise ValidationError(detail or payload or "Could not save.")
    return Response(payload, status=resp.status_code)


class _PettyView(V1ViewMixin, APIView):
    permission_classes = [IsAuthenticated, MatrixPermission]
    tab_code = TAB


class PettyExpenseListView(_PettyView):
    """The register and the figures above it, in one answer.

    Takes the same query the web register takes -- ``from``/``to``, ``month``,
    ``year``, ``status``, ``branch``, ``farm``, ``shed``, ``paid_from``,
    ``category``, ``q`` -- so the phone's quick filters are the web's filters
    and neither can drift into meaning something else.
    """

    def get(self, request):
        return _delegate(web.petty_expense_rows, request)


class PettyExpenseMastersView(_PettyView):
    """Everything the entry screen's pickers hold, asked for once.

    Branches, farms, sheds and open batches, categories and their ledgers, the
    cash boxes with their balances, payment modes and units -- already scoped
    to what this user may work in, by the same service the web form uses.
    """

    def get(self, request):
        return Response(web._masters(request.user))


class PettyExpenseDetailView(_PettyView):
    """One expense in full: its lines, its bills and what it posted."""

    def get(self, request, pk):
        return _delegate(web.petty_expense_detail, request, pk)


class PettyExpenseSaveView(_PettyView):
    """Save a draft, or save and post, exactly as the web form does.

    ``POST`` with no id creates; with an id it rewrites that expense. The body
    is the web form's body, and ``{"post": true}`` puts it on the books in the
    same call.
    """

    def post(self, request, pk=None):
        if pk is None:
            return _delegate(web.petty_expense_save, request)
        return _delegate(web.petty_expense_save, request, pk)


class PettyExpensePostView(_PettyView):
    def post(self, request, pk):
        return _delegate(web.petty_expense_post, request, pk)


class PettyExpenseCancelView(_PettyView):
    def post(self, request, pk):
        return _delegate(web.petty_expense_cancel, request, pk)


class PettyExpenseDeleteView(_PettyView):
    def post(self, request, pk):
        return _delegate(web.petty_expense_delete, request, pk)


class PettyExpenseAttachView(_PettyView):
    """The bill, photographed at the counter.

    Multipart, so the request is handed over without DRF having parsed it --
    the web view reads ``request.FILES`` itself.
    """

    def post(self, request, pk):
        return _delegate(web.petty_expense_attach, request, pk)

    def delete(self, request, pk, attachment_id):
        return _delegate(web.petty_expense_detach, request, pk, attachment_id)


class _VoucherView(V1ViewMixin, APIView):
    permission_classes = [IsAuthenticated, MatrixPermission]
    tab_code = VOUCHER_TAB


class VoucherListView(_VoucherView):
    """The register's rows.

    Takes the web register's own query -- ``type``, ``status``, ``sector``,
    ``date_from``, ``date_to``, ``q``, ``page``, ``page_size`` -- so the
    phone's filters and the browser's are the same filters.
    """

    def get(self, request):
        return _delegate(journal_web.VoucherListCreateAPI().get, request)


class VoucherCardsView(_VoucherView):
    """The four figures above the register, counted over the company."""

    def get(self, request):
        return _delegate(journal_web.voucher_cards, request)


class VoucherMastersView(_VoucherView):
    """Everything the entry screen's pickers hold, asked for once.

    The postable ledgers, the voucher types the engine mints numbers for, the
    sectors and the cost centres a line may carry -- the same four lists the
    browser's form fills itself from.
    """

    def get(self, request):
        from inventory.models import Warehouse

        from account.models import ChartOfAccount, OrganizationCentre, Voucher

        company = web.service.company()
        accounts = (ChartOfAccount.objects
                    .filter(company=company, is_postable=True, is_group=False,
                            status="Active", allow_manual_entry=True)
                    .order_by("code")
                    .values("id", "code", "description"))
        return Response({
            # A line may only be charged to a postable ledger that takes
            # manual entry: offering anything else is offering a refusal.
            "accounts": [{"id": a["id"], "code": a["code"], "name": a["description"]}
                         for a in accounts],
            "types": [{"value": value, "label": label}
                      for value, label in Voucher.TYPE_CHOICES],
            "sectors": list(Warehouse.objects.order_by("name").values("id", "name")),
            "centres": [{"id": c.id, "name": c.name}
                        for c in OrganizationCentre.objects
                        .filter(is_active=True, allow_manual_selection=True,
                                allow_children_only=False)
                        .order_by("name")],
        })


class VoucherSaveView(_VoucherView):
    """Write a voucher, or rewrite a draft, exactly as the browser does.

    ``POST`` with no id creates; with an id it rewrites that draft. The engine
    is what refuses an unbalanced entry, a group account or a locked year, so
    a refusal here reads the same on both screens.
    """

    def post(self, request, pk=None):
        if pk is None:
            return _delegate(journal_web.VoucherListCreateAPI().post, request)
        return _delegate(journal_web.VoucherDetailAPI().put, request, pk)


class VoucherDetailView(_VoucherView):
    """One voucher in full, with the lines that make it balance.

    A voucher without its lines is a number and a date; the lines are the
    thing anybody opens a voucher to read.
    """

    def get(self, request, pk):
        return _delegate(journal_web.VoucherDetailAPI().get, request, pk)

    def delete(self, request, pk):
        # Drafts only. A posted voucher is cancelled, never deleted -- the
        # web view says so itself, in its own words.
        return _delegate(journal_web.VoucherDetailAPI().delete, request, pk)


class VoucherPostView(_VoucherView):
    def post(self, request, pk):
        return _delegate(journal_web.VoucherPostAPI().post, request, pk)


class VoucherCancelView(_VoucherView):
    def post(self, request, pk):
        return _delegate(journal_web.VoucherCancelAPI().post, request, pk)


def write_urls() -> list:
    """URL patterns for the account transaction write endpoints."""
    return [
        path("account/petty-expenses/rows", PettyExpenseListView.as_view(),
             name="account-petty-expenses-rows"),
        path("account/petty-expenses/masters", PettyExpenseMastersView.as_view(),
             name="account-petty-expenses-masters"),
        path("account/petty-expenses/save", PettyExpenseSaveView.as_view(),
             name="account-petty-expenses-save-new"),
        path("account/petty-expenses/save/<int:pk>", PettyExpenseSaveView.as_view(),
             name="account-petty-expenses-save"),
        path("account/petty-expenses/<int:pk>", PettyExpenseDetailView.as_view(),
             name="account-petty-expenses-detail"),
        path("account/petty-expenses/<int:pk>/post", PettyExpensePostView.as_view(),
             name="account-petty-expenses-post"),
        path("account/petty-expenses/<int:pk>/cancel", PettyExpenseCancelView.as_view(),
             name="account-petty-expenses-cancel"),
        path("account/petty-expenses/<int:pk>/delete", PettyExpenseDeleteView.as_view(),
             name="account-petty-expenses-delete"),
        path("account/petty-expenses/<int:pk>/attach", PettyExpenseAttachView.as_view(),
             name="account-petty-expenses-attach"),
        path("account/petty-expenses/<int:pk>/attach/<int:attachment_id>",
             PettyExpenseAttachView.as_view(),
             name="account-petty-expenses-detach"),

        path("account/vouchers/rows", VoucherListView.as_view(),
             name="account-vouchers-rows"),
        path("account/vouchers/cards", VoucherCardsView.as_view(),
             name="account-vouchers-cards"),
        path("account/vouchers/masters", VoucherMastersView.as_view(),
             name="account-vouchers-masters"),
        path("account/vouchers/save", VoucherSaveView.as_view(),
             name="account-vouchers-save-new"),
        path("account/vouchers/save/<int:pk>", VoucherSaveView.as_view(),
             name="account-vouchers-save"),
        path("account/vouchers/<int:pk>/full", VoucherDetailView.as_view(),
             name="account-vouchers-detail"),
        path("account/vouchers/<int:pk>/post", VoucherPostView.as_view(),
             name="account-vouchers-post"),
        path("account/vouchers/<int:pk>/cancel", VoucherCancelView.as_view(),
             name="account-vouchers-cancel"),
    ]
