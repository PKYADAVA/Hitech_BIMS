"""Automatic sub-ledger creation.

Whenever a party/master record is created (customer, supplier, bank,
employee, warehouse), a matching postable ledger appears under the correct
control group of the company's chart of accounts:

    Customer  -> Accounts Receivable / <name>
    Supplier  -> Accounts Payable / <name>
    Bank      -> Bank Accounts / <name>
    Employee  -> Salary Payable / <name>  and  Employee Advances / <name>
    Warehouse -> Inventory / <name>

Ledgers link back to their source row via a generic FK, so renames propagate
and duplicates are impossible. Creation is skipped silently when the company
has no generated COA yet (the generator's bank step backfills banks; other
masters get ledgers from the next save once the COA exists).
"""
import logging

from django.contrib.contenttypes.models import ContentType

from account.models import ChartOfAccount, CompanyProfile
from .code_generator import AccountCodeGenerator

logger = logging.getLogger(__name__)


def sync_ledger(instance, name, anchor_roles, company=None):
    """Ensure one ledger per anchor role exists for *instance*; sync its name.

    Returns the list of ledger accounts. No-op when the COA/anchors are not
    generated yet. Never raises - master data saves must not fail because of
    ledger bookkeeping.
    """
    try:
        company = company or CompanyProfile.objects.filter(pk=1).first()
        if company is None or not name:
            return []
        ct = ContentType.objects.get_for_model(type(instance))
        codegen = AccountCodeGenerator(company)
        ledgers = []
        for role in anchor_roles:
            anchor = ChartOfAccount.objects.filter(company=company, system_role=role).first()
            if anchor is None:
                continue
            if not anchor.is_group:
                # Legacy/imported anchors may be plain leaves; promote them so
                # sub-ledgers can live underneath.
                anchor.is_group = True
                anchor.save()
            existing = ChartOfAccount.all_objects.filter(
                company=company,
                source_content_type=ct,
                source_object_id=instance.pk,
                parent=anchor,
            ).first()
            if existing:
                if existing.description != name:
                    existing.description = name
                    existing.save()
                ledgers.append(existing)
                continue
            ledger = ChartOfAccount(
                company=company,
                parent=anchor,
                code=codegen.next_code(parent=anchor, is_group=False),
                description=name,
                account_type=anchor.account_type,
                account_group=anchor.account_group,
                currency=anchor.currency,
                is_group=False,
                is_postable=True,
                system_generated=True,
            )
            ledger.source = instance
            ledger.save()
            ledgers.append(ledger)
        return ledgers
    except Exception:
        logger.exception(
            "Auto-ledger sync failed for %s #%s", type(instance).__name__, instance.pk
        )
        return []
