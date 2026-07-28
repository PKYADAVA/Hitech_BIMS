"""Sales domain — mobile API v1 resources.

Mirrors the web Sales module. Master data (customer groups, customers, sales
price list, shipping addresses) gets full CRUD via the generic form; the sales
invoice carries line-item children + GST side-effects the generic mobile form
can't author safely, so it (and its items) are exposed **read-only**.

Registered under ``/api/v1/sales/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from api.viewsets import register_model

from .models import (
    Customer,
    CustomerGroup,
    CustomerShippingAddress,
    SalesInvoice,
    SalesInvoiceItem,
    SalesPriceMaster,
    SalesReceipt,
)


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
