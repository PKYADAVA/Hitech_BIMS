"""Permission classes for the mobile API.

The web app authorizes by *page*: ``WebAccessMiddleware`` maps a URL name to a
tab right. This module used to say that model does not apply to resource APIs,
and left ``IsAuthenticated`` as the whole policy. It does apply, and leaving it
out meant any valid token could create, edit and delete across 54 writable
resources regardless of the group matrix governing the same data in the web app
— the API was a way round the entire permission system.

``MatrixPermission`` closes that by mapping a resource to the tab that owns it
and the HTTP method to an action the matrix already understands. Data scoping
(branch / farm / warehouse ownership) is applied separately, on the queryset —
see ``api.viewsets``.

``ReadOnlyOrStaff`` remains for master/reference data that mobile should read
but not mutate.
"""
from __future__ import annotations

import logging

from django.conf import settings
from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS

__all__ = ["IsAuthenticated", "ReadOnlyOrStaff", "MatrixPermission", "MODEL_TABS"]

logger = logging.getLogger(__name__)


class ReadOnlyOrStaff(BasePermission):
    """Anyone authenticated may read; only staff may write."""

    def has_permission(self, request, view) -> bool:
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user.is_staff or request.user.is_superuser)


METHOD_ACTIONS = {
    "GET": "view", "HEAD": "view", "OPTIONS": "view",
    "POST": "add", "PUT": "edit", "PATCH": "edit", "DELETE": "delete",
}

#: "app_label.ModelName" -> the tab code that owns it.
#:
#: Only what is genuinely one-to-one. A wrong entry refuses a request the web
#: app would allow, which is worse than an unmapped one, so anything ambiguous
#: is left out and turns up in the audit instead.
MODEL_TABS = {
    # Broiler
    "broiler.Region": "region",
    "broiler.Branch": "branch_template",
    "broiler.Supervisor": "supervisor_template",
    "broiler.BroilerLine": "broiler_line",
    "broiler.BroilerFarm": "branch_farm",
    "broiler.BroilerFarmShed": "broiler_farm_shed",
    "broiler.BroilerBatch": "broiler_batch",
    "broiler.FarmerGroup": "farmer_group",
    "broiler.Farmer": "branch_farm",
    "broiler.DailyEntry": "daily_entry_list",
    "broiler.BirdSale": "bird_sale_list",
    "broiler.BirdSaleReceipt": "bird_sale_receipt_list",
    "broiler.BroilerDisease": "broiler_disease",
    "broiler.Breed": "breed",
    "broiler.BreedStandard": "breed_standard",
    "broiler.FarmLocationCapture": "farm_location_capture_list",
    # Inventory
    "inventory.Item": "items",
    "inventory.ItemCategory": "item_category",
    "inventory.Warehouse": "warehouse",
    "inventory.StockTransfer": "stock_transfer_list",
    "inventory.StockIssue": "stock_issue_list",
    "inventory.StockReceive": "stock_receive_list",
    "inventory.InventoryAdjustment": "inventory_adjustment_list",
    "inventory.MedicineTransfer": "medicine_transfer_list",
    # Purchase
    "purchase.Supplier": "supplier",
    "purchase.VendorGroup": "vendor_groups",
    "purchase.GeneralPurchase": "general_purchase_list",
    "purchase.ChicksPurchase": "chicks_purchase_list",
    "purchase.DebitNote": "debit_note_list",
    "purchase.CreditNote": "credit_note_list",
    # Sales
    "sales.Customer": "customer",
    "sales.CustomerGroup": "customer_groups",
    "sales.SalesInvoice": "sales_invoice_list",
    # Hatchery
    "hatchery.EggPurchase": "egg_purchase_list",
    "hatchery.ChickSale": "chick_sale_list",
    "hatchery.DeliveryChallan": "delivery_challan_list",
    # Account
    "account.ChartOfAccount": "coa",
    "account.Voucher": "vouchers",
    "account.FinancialYear": "fin_year",
    "account.BankCashMaster": "bank_cash",
    # HR
    "hr.Employee": "employee_list",
    "hr.Designation": "designation",
}


def model_for_view(view):
    model = getattr(getattr(view, "queryset", None), "model", None)
    if model is None:
        serializer = getattr(view, "serializer_class", None)
        model = getattr(getattr(serializer, "Meta", None), "model", None)
    return model


def tab_for_view(view):
    """The tab a viewset belongs to, or None when it is not mapped yet.

    An explicit ``tab_code`` on the viewset wins, so a resource can opt in
    without waiting for the map.
    """
    explicit = getattr(view, "tab_code", None)
    if explicit:
        return explicit
    model = model_for_view(view)
    if model is None:
        return None
    return MODEL_TABS.get(f"{model._meta.app_label}.{model.__name__}")


class MatrixPermission(BasePermission):
    """Hold an API request to the same matrix the web app uses.

    Resources with no tab mapped yet are **recorded, not refused**, exactly as
    the middleware handles the unmapped URL surface: filling the map in blind
    would break the mobile client for endpoints nobody has claimed. Set
    ``WEB_ACCESS_ENFORCE=True`` once ``manage.py webaccess_audit`` is clean.
    """

    message = "You do not have permission to use this resource."

    def has_permission(self, request, view) -> bool:
        from user.access import user_can

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False

        tab = tab_for_view(view)
        if tab is None:
            return self._unmapped(request, view, user)

        action = METHOD_ACTIONS.get(request.method, "view")
        if user_can(user, tab, action):
            return True
        self._record(request, view, user, "denied", tab, action)
        return False

    def _unmapped(self, request, view, user) -> bool:
        self._record(request, view, user, "unmapped", "", "")
        if not getattr(settings, "WEB_ACCESS_ENFORCE", False):
            return True             # audit only — the API behaves as before
        logger.warning("api: refusing unmapped resource %s for %s",
                       view.__class__.__name__, user.get_username())
        return False

    def _record(self, request, view, user, verdict, tab, action) -> None:
        from django.core.cache import cache
        from django.db.models import F

        from user.models import WebAccessAudit

        name = f"api:{view.__class__.__name__}"
        username = user.get_username()
        throttle = f"wa:audit:{verdict}:{name}:{request.method}:{username}"
        if cache.get(throttle):
            return
        cache.set(throttle, 1, 600)
        try:
            updated = WebAccessAudit.objects.filter(
                url_name=name, method=request.method, verdict=verdict,
                username=username).update(hits=F("hits") + 1)
            if not updated:
                WebAccessAudit.objects.create(
                    url_name=name, method=request.method, verdict=verdict,
                    username=username, path=request.path[:300],
                    view=f"{view.__class__.__module__}.{view.__class__.__name__}"[:200],
                    tab_code=tab, action=action)
        except Exception:
            # Auditing must never be why an API call fails.
            logger.exception("api: could not record %s for %s", verdict, name)
