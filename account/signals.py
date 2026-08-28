"""Signal receivers that keep sub-ledgers in sync with master records.

Registered from AccountConfig.ready(). Receivers use lazy sender strings so
the account app never imports the other apps' modules at startup.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from account.services.auto_ledger import sync_branch_organization_centre, sync_ledger


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


@receiver(post_save, sender='broiler.Farmer', dispatch_uid='coa_ledger_farmer')
def farmer_ledger(sender, instance, **kwargs):
    # A farmer is a party we owe growing charges to, so they get a ledger under
    # their own control group exactly as a supplier gets one under Accounts
    # Payable. Their name field is farmer_name, not name.
    sync_ledger(instance, instance.farmer_name, ['FARMER_PAYABLE'])


@receiver(post_save, sender='hr.Employee', dispatch_uid='coa_ledger_employee')
def employee_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.full_name, ['SALARY_PAYABLE', 'EMPLOYEE_ADVANCE'])


@receiver(post_save, sender='inventory.Warehouse', dispatch_uid='coa_ledger_warehouse')
def warehouse_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['INVENTORY'])


@receiver(post_save, sender='broiler.Branch', dispatch_uid='organization_centre_branch_sync')
def branch_cost_center(sender, instance, **kwargs):
    sync_branch_organization_centre(instance)

# Business documents no longer auto-post vouchers, so there is nothing to
# cancel when one is deleted. Journal vouchers are entered manually only.
