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
    "broiler.MedicineVaccineEntry": "medicine_entry_list",
    "broiler.GrowingChargeScheme": "growing_charge",
    "broiler.GrowingChargeSettlement": "gc_settlement",
    "broiler.FarmerFarmSetupRequest": "farmer_farm_setup_request_list",
    # Photos belong to the entry they are attached to — same tab, so a user who
    # may see the record may see its pictures and no one else can.
    "broiler.BirdSalePhoto": "bird_sale_list",
    "broiler.DailyEntryPhoto": "daily_entry_list",
    # Inventory
    "inventory.Item": "items",
    "inventory.ItemCategory": "item_category",
    "inventory.Warehouse": "warehouse",
    "inventory.StockTransfer": "stock_transfer_list",
    "inventory.StockIssue": "stock_issue_list",
    "inventory.StockReceive": "stock_receive_list",
    "inventory.InventoryAdjustment": "inventory_adjustment_list",
    "inventory.MedicineTransfer": "medicine_transfer_list",
    "inventory.Sector": "sector",
    "inventory.UnitOfMeasurement": "unit_of_measurement",
    "inventory.ItemPriceList": "item_price_list",
    # Purchase
    "purchase.Supplier": "supplier",
    "purchase.VendorGroup": "vendor_groups",
    "purchase.GeneralPurchase": "general_purchase_list",
    "purchase.ChicksPurchase": "chicks_purchase_list",
    "purchase.DebitNote": "debit_note_list",
    "purchase.CreditNote": "credit_note_list",
    "purchase.SupplierPayment": "payment_list",
    "purchase.TaxMaster": "tax_master",
    # Line items carry the tab of the document they belong to.
    "purchase.GeneralPurchaseItem": "general_purchase_list",
    "purchase.ChicksPurchaseItem": "chicks_purchase_list",
    "purchase.SupplierPaymentLine": "payment_list",
    # Sales
    "sales.Customer": "customer",
    "sales.CustomerGroup": "customer_groups",
    "sales.SalesInvoice": "sales_invoice_list",
    "sales.SalesInvoiceItem": "sales_invoice_list",
    "sales.SalesReceipt": "sales_receipt_list",
    "sales.SalesPriceMaster": "sales_price_master",
    # Hatchery
    "hatchery.EggPurchase": "egg_purchase_list",
    "hatchery.ChickSale": "chick_sale_list",
    "hatchery.DeliveryChallan": "delivery_challan_list",
    "hatchery.EggGrading": "egg_grading_list",
    "hatchery.HatchSetting": "hatchery_list",
    "hatchery.TraySetting": "tray_set_list",
    "hatchery.HatchEntry": "hatch_entry_list",
    "hatchery.ChangeRequest": "change_requests",
    "hatchery_master.ExpenseType": "expense_type_list",
    "hatchery_master.HatcheryExpense": "hatchery_expense_list",
    "hatchery.EggPurchaseItem": "egg_purchase_list",
    "hatchery.ChickSaleItem": "chick_sale_list",
    "hatchery.DeliveryChallanItem": "delivery_challan_list",
    # Account
    "account.ChartOfAccount": "coa",
    "account.Voucher": "vouchers",
    "account.FinancialYear": "fin_year",
    "account.BankCashMaster": "bank_cash",
    "account.OrganizationCentre": "organization_centre",
    "account.CompanyProfile": "company_profile",
    "account.TermsConditions": "terms",
    # HR
    "hr.Employee": "employee_list",
    "hr.Designation": "designation",
    "hr.Attendance": "employee_attendance",
    "hr.EmployeeLeave": "leave_employee",
    "hr.LeaveSelectedDate": "employee_leave_details",
    "hr.Payroll": "payroll",
    "hr.Group": "employee_group",
    # SMS
    "notification.SmsTemplate": "sms_templates",
    "notification.SmsMessage": "sms_history",
    "notification.SmsSettings": "sms_settings",
    # Hatchery equipment. MASTER_REFERENCE_TABS already names these three, but
    # a tab there does nothing until the model resolves to it — unmapped, they
    # were reaching the picker through the unmapped-is-allowed fallback, which
    # the WEB_ACCESS_ENFORCE rollout removes. The Hatch Setting form's hatchery
    # picker would have gone blank on the day that flag was turned on.
    "hatchery_master.Hatchery": "hatchery_master_list",
    "hatchery_master.Hatcher": "hatcher_list",
    "hatchery_master.Setter": "setter_list",
}


#: Resources with no tab because no web page owns them.
#:
#: These pass today only because an unmapped resource is allowed, which is the
#: audit's fallback and goes away the day ``WEB_ACCESS_ENFORCE`` is turned on —
#: at which point every one of these screens would start refusing everybody.
#: Naming them converts an accidental pass into a decided one, so the flag can
#: be flipped without taking them down.
#:
#: The reasons are ``mobile_access.UNGATED_SCREENS``', already reviewed there:
#: no web page exists, so there is no permission to inherit, and a driver's own
#: vehicles are their reference data — the API narrows each of these to the
#: caller rather than leaving them wide.
UNGATED_MODELS = {
    "hr.Department",
    "hr.Shift",
    "hr.EmployeeVehicle",
    # Trips and their visits are narrowed to the caller by the viewset
    # itself ("the list shows their trips and no one else's"), so the
    # Home screen's own-round widget must not need the trip *report*
    # right to ask. Mapping them to that tab took a supervisor's own
    # day away from them, which is how this was found.
    "hr.SupervisorTrip",
    "hr.SupervisorTripVisit",
    "purchase.CreditTerm",
    "purchase.SupplierShippingAddress",
    "sales.CustomerShippingAddress",
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

        # Reading a master is part of using the transaction that asks for it.
        # The phone's Daily Entry screen needs farms, batches and supervisors
        # to fill its pickers; refusing those because the user was not also
        # given the Broiler Farm master left the screen open with every
        # dropdown empty and nothing to say why. Same rule the web middleware
        # applies to the master JSON feeds — read is opened, writing a master
        # still needs that master's own rights, and the rows that come back are
        # still narrowed by the data scope.
        from user.access import MASTER_REFERENCE_TABS

        if action == "view" and tab in MASTER_REFERENCE_TABS:
            return True

        # Parties and ledgers are not in that set and must not be — they carry
        # contact, credit and payroll columns, and it opens a read to everyone
        # with a login. They get the narrower rule instead: the transaction the
        # picker belongs to is what entitles the read, exactly as it does on the
        # web, where the form is handed its customers through view context and
        # never asks the master. `picker_only` narrows the row to identity.
        from user.access import picker_read_allowed
        from user.services.mobile_access import mobile_can

        if (action == "view" and not user_can(user, tab, action)
                and picker_read_allowed(
                    user, tab, entitles=lambda code: mobile_can(user, code, "view"))):
            request.picker_only = True
            return True

        if not user_can(user, tab, action):
            self._record(request, view, user, "denied", tab, action)
            return False

        # Second gate, phone only: Mobile Access narrows what the matrix allows
        # — a whole module, or one action on one screen. Subtractive, so it is
        # only ever consulted after the matrix has already said yes.
        from user.services.mobile_access import mobile_can

        if not mobile_can(user, tab, action):
            self._record(request, view, user, "denied", tab, action)
            return False
        return True

    def _unmapped(self, request, view, user) -> bool:
        model = model_for_view(view)
        if model is not None and (
                f"{model._meta.app_label}.{model.__name__}" in UNGATED_MODELS):
            return True             # decided, not merely unmapped

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
