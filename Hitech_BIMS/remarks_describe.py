"""Auto-fill a transaction's `remarks` with a generated description when blank.

A per-model registry (`DESCRIBERS`) maps each transaction model to a function
that builds a short human description from the fields available at save time
(party / mode / amount / item / farm). A single project-wide `pre_save`
receiver fills `remarks` ONLY when the user left it empty — it never overwrites
typed text. The generated text is Title-Cased via `to_title_case`, so it is
consistent with the global formatting rule regardless of signal order.

Note: the auto document number (bill/receipt/payment no.) is blank at the first
`pre_save`, so descriptions intentionally omit it.
"""
from django.db.models.signals import pre_save
from django.dispatch import receiver

from Hitech_BIMS.text_format import to_title_case


def _amt(v):
    """Grouped amount without the ₹ symbol; drops a trailing .00."""
    if v in (None, ""):
        return ""
    from account.services.narration import format_inr
    s = format_inr(v).replace("₹", "")
    return s[:-3] if s.endswith(".00") else s


# --- per-model description builders (fields available at save time) ---

def _d_payment_line(o):
    party = o.supplier.name if o.supplier_id else ""
    return f"Payment to {party} {_amt(o.amount)} via {o.mode}"


def _d_receipt(o):  # BirdSaleReceipt / SalesReceipt / ChickSaleReceipt
    party = ""
    if getattr(o, "customer_id", None):
        party = o.customer.name
    elif getattr(o, "farmer_id", None):
        party = o.farmer.farmer_name
    return f"Receipt from {party} {_amt(o.amount)} via {o.mode}"


def _d_bird_sale(o):
    party = o.customer.name if o.customer_id else (o.farmer.farmer_name if o.farmer_id else "")
    return f"Bird sale to {party} {_amt(o.birds)} birds {_amt(o.net_weight)} kg"


def _d_daily_entry(o):
    farm = o.farm.farm_name if o.farm_id else ""
    return f"Daily entry {farm} age {o.age_days} mortality {o.mortality} culls {o.culls}"


def _d_medicine_entry(o):
    farm = o.farm.farm_name if o.farm_id else ""
    item = o.item.description if o.item_id else ""
    return f"Medicine {item} {_amt(o.qty)} {farm}"


def _d_stock_transfer(o):
    item = o.item.description if o.item_id else ""
    src = o.from_warehouse.name if o.from_warehouse_id else (o.from_farm.farm_name if o.from_farm_id else "")
    dst = o.to_warehouse.name if o.to_warehouse_id else (o.to_farm.farm_name if o.to_farm_id else "")
    return f"{item} {_amt(o.quantity)} from {src} to {dst}"


def _d_general_purchase(o):
    return f"Purchase from {o.supplier.name if o.supplier_id else ''} {_amt(o.net_amount)}"


def _d_chicks_purchase(o):
    return f"Chicks purchase from {o.supplier.name if o.supplier_id else ''} {_amt(o.net_amount)}"


def _d_egg_purchase(o):
    return f"Egg purchase from {o.supplier.name if o.supplier_id else ''}"


def _d_chick_sale(o):
    return f"Chick sale to {o.customer.name if o.customer_id else ''} {_amt(o.final_amount)}"


def _d_sales_invoice(o):
    return f"Sales invoice to {o.customer.name if o.customer_id else ''} {_amt(o.net_amount)}"


def _d_note(o):  # DebitNote / CreditNote
    kind = o._meta.model_name.replace("note", " note")   # "debit note" / "credit note"
    return f"{kind} {o.supplier.name if o.supplier_id else ''} {_amt(o.amount)}"


DESCRIBERS = {
    "purchase.SupplierPaymentLine": _d_payment_line,
    "broiler.BirdSaleReceipt": _d_receipt,
    "sales.SalesReceipt": _d_receipt,
    "hatchery.ChickSaleReceipt": _d_receipt,
    "broiler.BirdSale": _d_bird_sale,
    "broiler.DailyEntry": _d_daily_entry,
    "broiler.MedicineVaccineEntry": _d_medicine_entry,
    "inventory.StockTransfer": _d_stock_transfer,
    "purchase.GeneralPurchase": _d_general_purchase,
    "purchase.ChicksPurchase": _d_chicks_purchase,
    "hatchery.EggPurchase": _d_egg_purchase,
    "hatchery.ChickSale": _d_chick_sale,
    "sales.SalesInvoice": _d_sales_invoice,
    "purchase.DebitNote": _d_note,
    "purchase.CreditNote": _d_note,
}


def describe(instance):
    """Title-Cased description for `instance`, or None if no builder / no data."""
    fn = DESCRIBERS.get(instance._meta.label)
    if not fn:
        return None
    try:
        text = (fn(instance) or "").strip()
    except Exception:
        return None
    return to_title_case(text) if text else None


@receiver(pre_save, dispatch_uid="autofill_remarks")
def _fill_remarks(sender, instance, **kwargs):
    """Fill `remarks` with a generated description only when the user left it
    blank — never overwrites typed text."""
    if instance._meta.label not in DESCRIBERS:
        return
    cur = getattr(instance, "remarks", None)
    if isinstance(cur, str) and cur.strip():
        return
    desc = describe(instance)
    if desc:
        instance.remarks = desc
