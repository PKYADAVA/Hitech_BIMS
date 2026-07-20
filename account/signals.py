"""Signal receivers that keep sub-ledgers in sync with master records.

Registered from AccountConfig.ready(). Receivers use lazy sender strings so
the account app never imports the other apps' modules at startup.
"""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from account.services.auto_ledger import sync_branch_cost_center, sync_ledger


@receiver(post_save, sender='sales.Customer', dispatch_uid='coa_ledger_customer')
def customer_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['ACCOUNTS_RECEIVABLE'])


@receiver(post_save, sender='purchase.Supplier', dispatch_uid='coa_ledger_supplier')
def supplier_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['ACCOUNTS_PAYABLE'])


@receiver(post_save, sender='account.BankCashMaster', dispatch_uid='coa_ledger_bank_cash')
def bank_cash_ledger(sender, instance, **kwargs):
    anchor_role = 'CASH' if instance.is_cash else 'BANK_ACCOUNTS'
    sync_ledger(instance, instance.name, [anchor_role])


@receiver(post_save, sender='hr.Employee', dispatch_uid='coa_ledger_employee')
def employee_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.full_name, ['SALARY_PAYABLE', 'EMPLOYEE_ADVANCE'])


@receiver(post_save, sender='inventory.Warehouse', dispatch_uid='coa_ledger_warehouse')
def warehouse_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['INVENTORY'])


@receiver(post_save, sender='broiler.Branch', dispatch_uid='cost_center_branch_sync')
def branch_cost_center(sender, instance, **kwargs):
    sync_branch_cost_center(instance)


# Deleting a business document cancels its auto-posted voucher (the voucher
# itself is never deleted - the books keep the cancelled record).

@receiver(post_delete, sender='hatchery.EggPurchase', dispatch_uid='coa_unpost_egg_purchase')
def egg_purchase_deleted(sender, instance, **kwargs):
    from account.services.auto_posting import cancel_for_document
    try:
        cancel_for_document(instance, f"Egg purchase {instance.transaction_no} deleted")
    except Exception:  # never block the delete
        import logging
        logging.getLogger(__name__).exception("Could not cancel voucher for deleted egg purchase")


@receiver(post_delete, sender='hatchery.ChickSale', dispatch_uid='coa_unpost_chick_sale')
def chick_sale_deleted(sender, instance, **kwargs):
    from account.services.auto_posting import cancel_for_document
    try:
        cancel_for_document(instance, f"Chick sale {instance.bill_no} deleted")
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Could not cancel voucher for deleted chick sale")
