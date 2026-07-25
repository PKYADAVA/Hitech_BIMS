"""Purchase domain — mobile API v1 resources.

Mirrors the web Purchase module. Master data + flat debit/credit notes get full
CRUD via the generic form; the purchase/payment transactions carry line-item
children + stock/ledger side-effects the generic mobile form can't author
safely, so they (and their line tables) are exposed **read-only**.

Registered under ``/api/v1/purchase/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from api.viewsets import register_model

from .models import (
    ChicksPurchase,
    ChicksPurchaseItem,
    CreditNote,
    CreditTerm,
    DebitNote,
    GeneralPurchase,
    GeneralPurchaseItem,
    Supplier,
    SupplierPayment,
    SupplierPaymentLine,
    SupplierShippingAddress,
    TaxMaster,
    VendorGroup,
)


def register(router) -> None:
    # --- Master data (full CRUD; list also serves as picker data) -------
    register_model(router, "purchase/vendor-groups", VendorGroup,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "purchase/suppliers", Supplier,
                   search_fields=["code", "name", "mobile", "gstin", "place"],
                   ordering=["name"])
    register_model(router, "purchase/credit-terms", CreditTerm,
                   search_fields=["term"], ordering=["term"])
    register_model(router, "purchase/tax-masters", TaxMaster,
                   search_fields=["tax_code", "description"], ordering=["tax_code"])
    register_model(router, "purchase/shipping-addresses", SupplierShippingAddress,
                   search_fields=["label", "contact_person", "mobile"])

    # --- Debit / credit notes (flat docs — full CRUD) -------------------
    register_model(router, "purchase/debit-notes", DebitNote,
                   search_fields=["note_no", "against_bill"], ordering=["-id"])
    register_model(router, "purchase/credit-notes", CreditNote,
                   search_fields=["note_no", "against_bill"], ordering=["-id"])

    # --- Transactions (read-only: line-item children + ledger effects) --
    register_model(router, "purchase/general-purchases", GeneralPurchase, read_only=True,
                   search_fields=["purchase_no", "bill_no", "vehicle_no"], cursor=True)
    register_model(router, "purchase/chicks-purchases", ChicksPurchase, read_only=True,
                   search_fields=["purchase_no", "bill_no"], cursor=True)
    register_model(router, "purchase/supplier-payments", SupplierPayment, read_only=True,
                   search_fields=["payment_no"], cursor=True)

    # --- Line items (read-only; shown inside their parent's detail) -----
    register_model(router, "purchase/general-purchase-items", GeneralPurchaseItem, read_only=True)
    register_model(router, "purchase/chicks-purchase-items", ChicksPurchaseItem, read_only=True)
    register_model(router, "purchase/supplier-payment-lines", SupplierPaymentLine, read_only=True)
