"""Account domain — mobile API v1 resources.

Mirrors the web Accounts module. Financial years and terms & conditions are
simple enough for full CRUD from the mobile form; the chart of accounts, bank /
cash masters, organization centres, company profile and journal vouchers are
exposed **read-only** — they're hierarchical, singleton or carry posted line
items whose integrity the generic mobile form can't preserve. All plumbing
(envelope, auth, pagination, N+1-safe querysets, ``updated_since`` delta sync)
comes from ``api.viewsets``.

Registered under ``/api/v1/account/…`` by :func:`register` (called from
``api/urls.py``).
"""
from __future__ import annotations

from api.viewsets import register_model

from .models import (
    BankCashMaster,
    ChartOfAccount,
    CompanyProfile,
    FinancialYear,
    OrganizationCentre,
    TermsConditions,
    Voucher,
)


def register(router) -> None:
    # --- Master data (full CRUD) ----------------------------------------
    register_model(router, "account/financial-years", FinancialYear,
                   ordering=["-start_date"])
    register_model(router, "account/terms", TermsConditions,
                   search_fields=["type", "party_type"], ordering=["-id"])

    # --- Master data (read-only: hierarchical / singleton) --------------
    register_model(router, "account/chart-of-accounts", ChartOfAccount, read_only=True,
                   search_fields=["code", "description"], ordering=["code"])
    register_model(router, "account/bank-cash", BankCashMaster, read_only=True,
                   search_fields=["code", "name"], ordering=["name"])
    register_model(router, "account/organization-centres", OrganizationCentre, read_only=True,
                   search_fields=["code", "name"], ordering=["code"])
    register_model(router, "account/company-profiles", CompanyProfile, read_only=True,
                   search_fields=["name", "gstin", "pan"], ordering=["name"])

    # --- Transactions (read-only: balanced voucher lines + posting) -----
    register_model(router, "account/vouchers", Voucher, read_only=True,
                   search_fields=["voucher_no", "reference"], cursor=True)
