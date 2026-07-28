"""Shared helper: the Chart-of-Account ledgers backed by a Bank/Cash Master.

Payment / receipt "cash or bank" account dropdowns across the ERP should all
source from here, so they only ever list the accounts defined in the Bank/Cash
Master (excluding generic COAs and the internal __VERIFY_* anchors).
"""
from django.contrib.contenttypes.models import ContentType


def bank_cash_accounts():
    from account.models import ChartOfAccount, BankCashMaster
    ct = ContentType.objects.get_for_model(BankCashMaster)
    return (ChartOfAccount.objects
            .filter(source_content_type=ct,
                    source_object_id__in=BankCashMaster.objects.values("id"))
            .order_by("code"))


def ledger_for_bank_cash(bank_cash):
    """The (active) ChartOfAccount ledger for a BankCashMaster, or None."""
    from account.models import ChartOfAccount, BankCashMaster
    if not bank_cash:
        return None
    ct = ContentType.objects.get_for_model(BankCashMaster)
    return ChartOfAccount.objects.filter(
        source_content_type=ct, source_object_id=bank_cash.pk).first()


def _scoped_modes(context):
    """Active PaymentMode queryset scoped to a form context: 'payment' ->
    Payment/Both, 'receipt' -> Receipt/Both, None -> all active."""
    from account.models import PaymentMode
    qs = PaymentMode.objects.filter(is_active=True)
    if context == "payment":
        qs = qs.filter(applicable_for__in=["Payment", "Both"])
    elif context == "receipt":
        qs = qs.filter(applicable_for__in=["Receipt", "Both"])
    return qs.order_by("display_order", "name")


def active_payment_modes(context=None):
    """Active PaymentMode names for the payment/receipt mode dropdowns."""
    return list(_scoped_modes(context).values_list("name", flat=True))


def payment_mode_map(context=None):
    """{mode_name: <coa id or "">} for active Payment Modes — the Chart-of-Account
    ledger of the Bank/Cash account each mode maps to. A payment/receipt form uses
    this to auto-fill (and lock) the account when a mapped mode is chosen."""
    from account.models import ChartOfAccount, BankCashMaster
    ct = ContentType.objects.get_for_model(BankCashMaster)
    coa_by_bc = {}
    for coa_id, obj_id in ChartOfAccount.objects.filter(
            source_content_type=ct).values_list("id", "source_object_id"):
        coa_by_bc[str(obj_id)] = coa_id
    out = {}
    for pm in _scoped_modes(context).prefetch_related("bank_cash"):
        ids = [coa_by_bc.get(str(bc_id)) for bc_id in pm.bank_cash.values_list("id", flat=True)]
        out[pm.name] = [i for i in ids if i]
    return out
