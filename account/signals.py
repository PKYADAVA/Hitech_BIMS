"""Signal receivers that keep sub-ledgers in sync with master records.

Registered from AccountConfig.ready(). Receivers use lazy sender strings so
the account app never imports the other apps' modules at startup.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from account.services.auto_ledger import sync_ledger


@receiver(post_save, sender='sales.Customer', dispatch_uid='coa_ledger_customer')
def customer_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['ACCOUNTS_RECEIVABLE'])


@receiver(post_save, sender='purchase.Supplier', dispatch_uid='coa_ledger_supplier')
def supplier_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['ACCOUNTS_PAYABLE'])


@receiver(post_save, sender='account.BankCode', dispatch_uid='coa_ledger_bank')
def bank_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.bank_name, ['BANK_ACCOUNTS'])


@receiver(post_save, sender='hr.Employee', dispatch_uid='coa_ledger_employee')
def employee_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.full_name, ['SALARY_PAYABLE', 'EMPLOYEE_ADVANCE'])


@receiver(post_save, sender='inventory.Warehouse', dispatch_uid='coa_ledger_warehouse')
def warehouse_ledger(sender, instance, **kwargs):
    sync_ledger(instance, instance.name, ['INVENTORY'])
