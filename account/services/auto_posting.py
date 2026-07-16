"""Automatic voucher posting for business documents.

Turns hatchery documents into balanced journal vouchers through the journal
service, so ledgers/trial balance reflect operations without manual entry:

    EggPurchase (Purchase voucher)
        Dr Egg Purchases (COGS)          gross item amount
        Dr freight account               freight (doc's freight_account or Freight Inward)
        Dr TCS Receivable                TCS amount
        Cr supplier AP ledger            bill amount           (payment_mode pay_later)
        Cr pay account                   bill amount           (payment_mode pay_in_bill)
        Cr pay account                   freight, when freight_type='Exclude'
                                         (paid separately, not part of the supplier bill)

    ChickSale (Sales voucher)
        Dr customer AR ledger / pay account   final amount
        Cr Chick Sales (income)               items amount
        Cr freight recovery                   freight, when 'Include in Bill'

Lifecycle: one Posted voucher per document. Re-posting after a document edit
cancels the old voucher (reason kept) and posts a fresh one; deleting the
document cancels its voucher. A document whose amounts are unchanged is left
alone. Posting failures are logged and never block the document save - the
``repost_documents`` management command backfills anything missed.
"""
import logging
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType

from account.models import ChartOfAccount, CompanyProfile, Voucher
from . import journal
from .auto_ledger import sync_ledger
from .code_generator import AccountCodeGenerator

logger = logging.getLogger(__name__)

# Role accounts the posting engine may need beyond the generated set:
# role -> (name, account type code, parent role)
ROLE_SPECS = {
    'EGG_PURCHASES': ("Egg Purchases", 'COGS', 'COGS_GROUP'),
    'CHICK_SALES': ("Chick Sales", 'INCOME', 'SALES'),
    'FREIGHT_INWARD': ("Freight Inward", 'COGS', 'COGS_GROUP'),
    'FREIGHT_RECOVERED': ("Freight Recovered", 'INCOME', 'OTHER_INCOME'),
    'TCS_RECEIVABLE': ("TCS Receivable", 'ASSET', 'TAX_INPUT_GROUP'),
}


def _company():
    return CompanyProfile.objects.filter(pk=1).first()


def ensure_role_account(company, role):
    """Find (or create under its anchor) the postable account for a role."""
    account = ChartOfAccount.objects.filter(company=company, system_role=role).first()
    if account:
        return account
    name, type_code, parent_role = ROLE_SPECS[role]
    parent = ChartOfAccount.objects.filter(company=company, system_role=parent_role).first()
    if parent is None:
        raise ValueError(
            f"Chart of accounts has no '{parent_role}' group - generate the COA first."
        )
    from account.models import AccountType
    account_type = AccountType.objects.get(code=type_code)
    account = ChartOfAccount(
        company=company,
        parent=parent,
        code=AccountCodeGenerator(company).next_code(parent=parent, account_type=account_type),
        description=name,
        account_type=account_type,
        account_group=parent.account_group,
        currency=parent.currency,
        is_group=False,
        is_postable=True,
        system_generated=True,
        system_role=role,
    )
    account.save()
    return account


def _party_ledger(company, party, name, anchor_role):
    ledgers = sync_ledger(party, name, [anchor_role], company=company)
    if not ledgers:
        raise ValueError(
            f"Could not create a ledger for {name} - is the chart of accounts generated?"
        )
    return ledgers[0]


def _existing_voucher(document):
    ct = ContentType.objects.get_for_model(type(document))
    return Voucher.objects.filter(
        source_content_type=ct, source_object_id=document.pk, status='Posted',
    ).first()


def cancel_for_document(document, reason):
    voucher = _existing_voucher(document)
    if voucher:
        journal.cancel_voucher(voucher, reason=reason[:255])
    return voucher


# -------------------------------------------------------------- line builders

def _egg_purchase_lines(company, doc):
    gross = Decimal(doc.gross_amount() or 0)
    freight = Decimal(doc.freight_amount or 0)
    tcs = Decimal(doc.tcs_amount() or 0)
    if gross <= 0:
        return None, None

    purchases = ensure_role_account(company, 'EGG_PURCHASES')
    freight_acct = doc.freight_account or (freight and ensure_role_account(company, 'FREIGHT_INWARD'))
    if doc.payment_mode == 'pay_in_bill':
        credit_acct = doc.pay_account
    else:
        credit_acct = _party_ledger(company, doc.supplier, doc.supplier.name, 'ACCOUNTS_PAYABLE')

    lines = [{'account': purchases.id, 'debit': gross, 'credit': 0,
              'narration': f"Eggs purchased ({doc.transaction_no})"}]
    if freight:
        lines.append({'account': freight_acct.id, 'debit': freight, 'credit': 0,
                      'narration': 'Freight'})
    if tcs:
        lines.append({'account': ensure_role_account(company, 'TCS_RECEIVABLE').id,
                      'debit': tcs, 'credit': 0, 'narration': f"TCS {doc.tcs_percent}%"})

    if doc.freight_type == 'Exclude' and freight:
        # Freight is not part of the supplier bill; it is paid separately.
        lines.append({'account': doc.pay_account.id, 'debit': 0, 'credit': freight,
                      'narration': 'Freight paid separately'})
        lines.append({'account': credit_acct.id, 'debit': 0, 'credit': gross + tcs,
                      'narration': f"Bill {doc.transaction_no}"})
    else:
        lines.append({'account': credit_acct.id, 'debit': 0, 'credit': gross + freight + tcs,
                      'narration': f"Bill {doc.transaction_no}"})
    return lines, f"Egg purchase {doc.transaction_no} - {doc.supplier.name}"


def _chick_sale_lines(company, doc):
    items_amount = Decimal(doc.items_amount() or 0)
    freight = Decimal(doc.freight_amount or 0) if doc.freight_type == 'Include in Bill' else Decimal(0)
    total = items_amount + freight
    if total <= 0:
        return None, None

    if doc.payment_mode == 'pay_in_bill' and doc.pay_account:
        debit_acct = doc.pay_account
    else:
        debit_acct = _party_ledger(company, doc.customer, doc.customer.name, 'ACCOUNTS_RECEIVABLE')

    lines = [{'account': debit_acct.id, 'debit': total, 'credit': 0,
              'narration': f"Bill {doc.bill_no}"}]
    lines.append({'account': ensure_role_account(company, 'CHICK_SALES').id,
                  'debit': 0, 'credit': items_amount,
                  'narration': f"Chicks sold ({doc.bill_no})"})
    if freight:
        freight_acct = doc.freight_account or ensure_role_account(company, 'FREIGHT_RECOVERED')
        lines.append({'account': freight_acct.id, 'debit': 0, 'credit': freight,
                      'narration': 'Freight billed'})
    return lines, f"Chick sale {doc.bill_no} - {doc.customer.name}"


BUILDERS = {
    'eggpurchase': ('Purchase', _egg_purchase_lines),
    'chicksale': ('Sales', _chick_sale_lines),
}


# ------------------------------------------------------------------ post API

def post_document(document, user=None):
    """(Re)post the voucher for a business document. Never raises."""
    try:
        company = _company()
        if company is None:
            return None
        key = type(document).__name__.lower()
        if key not in BUILDERS:
            raise ValueError(f"No posting rule for {type(document).__name__}")
        voucher_type, builder = BUILDERS[key]
        lines, narration = builder(company, document)

        existing = _existing_voucher(document)
        if lines is None:
            # Document no longer carries value; drop any stale voucher.
            if existing:
                journal.cancel_voucher(existing, user=user, reason="Document amount became zero")
            return None
        if existing and _same_lines(existing, lines) and existing.date == document.date:
            return existing
        if existing:
            journal.cancel_voucher(existing, user=user, reason="Document edited - replaced by new voucher")

        reference = getattr(document, 'transaction_no', '') or getattr(document, 'bill_no', '')
        voucher = journal.create_voucher(
            company=company,
            date=document.date,
            lines_data=lines,
            user=user,
            voucher_type=voucher_type,
            narration=narration,
            reference=reference,
            sector=getattr(document, 'warehouse', None),
            post=True,
            manual=False,
            system_generated=True,
        )
        voucher.source = document
        voucher.save(update_fields=['source_content_type', 'source_object_id'])
        return voucher
    except Exception:
        logger.exception(
            "Auto-posting failed for %s #%s - run 'manage.py repost_documents' after fixing.",
            type(document).__name__, document.pk,
        )
        return None


def _same_lines(voucher, lines):
    existing = sorted(
        (line.account_id, Decimal(line.debit), Decimal(line.credit))
        for line in voucher.lines.all()
    )
    incoming = sorted(
        (line['account'], Decimal(line['debit'] or 0).quantize(Decimal('0.01')),
         Decimal(line['credit'] or 0).quantize(Decimal('0.01')))
        for line in lines
    )
    return existing == incoming
