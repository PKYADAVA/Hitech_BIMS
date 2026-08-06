"""Sales domain — mobile API v1 resources.

Mirrors the web Sales module. Master data (customer groups, customers, sales
price list, shipping addresses) gets full CRUD via the generic form; the sales
invoice carries line-item children + GST side-effects the generic mobile form
can't author safely, so it (and its items) are exposed **read-only**.

Registered under ``/api/v1/sales/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin, register_model

from .models import (
    Customer,
    CustomerGroup,
    CustomerShippingAddress,
    SalesInvoice,
    SalesInvoiceItem,
    SalesPriceMaster,
    SalesReceipt,
)


class CustomerBalanceView(V1ViewMixin, APIView):
    """GET /api/v1/sales/customer-balance?customer=<id> — what one customer
    owes, for a form raising a document against them.

    The same payload the web Bird Sale and Delivery Challan forms fetch, from
    the same ``_customer_balance_row`` the Customer Balance report is built
    from — so the figure a supervisor is shown on the farm gate cannot differ
    from the figure the branch judges that customer by.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from .views import _customer_balance_row

        raw = (request.query_params.get("customer") or "").strip()
        customer = (Customer.objects.select_related("customer_group")
                    .filter(id=raw).first()) if raw.isdigit() else None
        if not customer:
            return Response({"balance": "", "label": "", "credit_limit": "",
                             "available": "", "limit_exceeded": ""})

        row = _customer_balance_row(customer, None, None, timezone.localdate())
        if row["debit"] > 0:
            label = "%s Dr" % row["debit"]           # customer owes us
        elif row["credit"] > 0:
            label = "%s Cr" % row["credit"]          # customer is in advance
        else:
            label = "0.00"
        return Response({
            "balance": str(row["debit"] - row["credit"]),
            "label": label,
            "credit_limit": str(row["credit_limit"]),
            "available": str(row["available"]),
            "limit_exceeded": str(row["limit_exceeded"]),
        })


def register(router) -> None:
    # --- Master data (full CRUD; list also serves as picker data) -------
    register_model(router, "sales/customer-groups", CustomerGroup,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "sales/customers", Customer,
                   search_fields=["code", "name", "mobile", "gstin", "place"],
                   ordering=["name"])
    register_model(router, "sales/prices", SalesPriceMaster,
                   search_fields=["item__item_code", "item__description"],
                   ordering=["-date", "-id"])
    register_model(router, "sales/shipping-addresses", CustomerShippingAddress,
                   search_fields=["label", "contact_person", "mobile"])

    # --- Invoices (read-only: line-item children + GST computations) ----
    register_model(router, "sales/invoices", SalesInvoice, read_only=True,
                   search_fields=["invoice_no", "reference_no", "vehicle_no", "gstin"],
                   cursor=True)
    register_model(router, "sales/invoice-items", SalesInvoiceItem, read_only=True)

    # --- Receipts (read-only list; created via the /sales/receipts/save API) --
    register_model(router, "sales/receipts", SalesReceipt, read_only=True,
                   search_fields=["receipt_no", "reference_no"], cursor=True)
