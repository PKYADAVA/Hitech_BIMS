"""Journal engine: voucher lifecycle, numbering, opening-voucher sync and
the ledger / trial-balance queries built purely from posted voucher lines.

Posting rules enforced here (and nowhere else, so every module goes through
this service):
- debits must equal credits and be greater than zero,
- lines may only hit postable, active, non-deleted leaf accounts of the
  voucher's company; manual entry additionally requires ``allow_manual_entry``,
- the voucher date must fall inside an Open financial year,
- posted vouchers are immutable; they can only be cancelled (kept forever),
- voucher numbers are assigned at posting time, sequential per
  company + financial year + voucher type.
"""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Sum
from django.utils import timezone

from account.models import ChartOfAccount, CostCenter, FinancialYear, Voucher, VoucherLine

VOUCHER_PREFIX = {
    'Journal': 'JV',
    'Payment': 'PV',
    'Receipt': 'RV',
    'Contra': 'CV',
    'Sales': 'SV',
    'Purchase': 'PUV',
    'Opening': 'OPV',
    'Closing': 'CLV',
}

TWO_PLACES = Decimal('0.01')


def _amount(value, label):
    try:
        amount = Decimal(str(value or '0')).quantize(TWO_PLACES)
    except (InvalidOperation, ValueError):
        raise ValidationError(f"Invalid amount '{value}' for {label}.")
    if amount < 0:
        raise ValidationError(f"Negative amount not allowed for {label}.")
    return amount


def parse_date(value):
    import datetime
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValidationError(f"Invalid date '{value}'. Use YYYY-MM-DD.")


def resolve_financial_year(date):
    fy = FinancialYear.objects.filter(start_date__lte=date, end_date__gte=date).first()
    if fy is None:
        raise ValidationError(f"No financial year covers {date}. Create it under Financial Year first.")
    return fy


def fy_label(fy):
    return f"{fy.start_date.year}-{str(fy.end_date.year)[-2:]}"


def _resolve_sector(sector):
    """Accept a Warehouse instance, pk, or falsy; raise on an unknown pk."""
    from inventory.models import Warehouse
    if not sector:
        return None
    if isinstance(sector, Warehouse):
        return sector
    resolved = Warehouse.objects.filter(pk=sector).first()
    if resolved is None:
        raise ValidationError("Selected sector (office/branch) was not found.")
    return resolved


def next_voucher_no(company, fy, voucher_type):
    prefix = VOUCHER_PREFIX.get(voucher_type, 'JV')
    label = fy_label(fy)
    existing = Voucher.objects.filter(
        company=company, financial_year=fy, voucher_type=voucher_type,
        voucher_no__isnull=False,
    ).values_list('voucher_no', flat=True)
    max_seq = 0
    for number in existing:
        try:
            max_seq = max(max_seq, int(number.rsplit('/', 1)[-1]))
        except (ValueError, IndexError):
            continue
    return f"{prefix}/{label}/{max_seq + 1:04d}"


def validate_lines(company, lines_data, manual=True):
    """Validate raw line dicts -> list of cleaned dicts. Raises ValidationError."""
    if not lines_data or len(lines_data) < 2:
        raise ValidationError("A voucher needs at least two lines (one debit, one credit).")
    cleaned = []
    total_debit = total_credit = Decimal('0')
    for index, raw in enumerate(lines_data, start=1):
        account = ChartOfAccount.objects.filter(pk=raw.get('account'), company=company).first()
        if account is None:
            raise ValidationError(f"Line {index}: account not found in this company.")
        if account.is_group or not account.is_postable:
            raise ValidationError(f"Line {index}: {account.code} - {account.description} is a group account and cannot be posted to.")
        if account.status != 'Active':
            raise ValidationError(f"Line {index}: {account.code} - {account.description} is inactive.")
        if manual and not account.allow_manual_entry:
            raise ValidationError(f"Line {index}: {account.code} - {account.description} does not allow manual entries.")
        debit = _amount(raw.get('debit'), f"line {index} debit")
        credit = _amount(raw.get('credit'), f"line {index} credit")
        if bool(debit) == bool(credit):
            raise ValidationError(f"Line {index}: enter either a debit or a credit amount (not both, not neither).")
        cost_center = None
        if raw.get('cost_center'):
            cost_center = CostCenter.objects.filter(pk=raw['cost_center'], company=company).first()
            if cost_center is None:
                raise ValidationError(f"Line {index}: cost center not found in this company.")
        total_debit += debit
        total_credit += credit
        cleaned.append({
            'account': account,
            'debit': debit,
            'credit': credit,
            'narration': str(raw.get('narration') or '')[:255],
            'cost_center': cost_center,
        })
    if total_debit != total_credit:
        raise ValidationError(
            f"Voucher is not balanced: debits {total_debit} != credits {total_credit}."
        )
    if total_debit == 0:
        raise ValidationError("Voucher total cannot be zero.")
    return cleaned


def _apply_narration_fields(voucher, user, auto_narration, narration_source):
    """Persist the auto-narration engine's audit trail (auto_narration/source/
    who-when), called from both create and update. No-op for callers (e.g.
    auto_posting.py) that don't pass these - they keep the model defaults."""
    if auto_narration is not None:
        voucher.auto_narration = auto_narration
    if narration_source is not None:
        voucher.narration_source = narration_source
        if narration_source == 'MANUAL':
            voucher.narration_edited_by = user
            voucher.narration_edited_at = timezone.now()
        else:
            voucher.narration_edited_by = None
            voucher.narration_edited_at = None


@transaction.atomic
def create_voucher(company, date, lines_data, user=None, voucher_type='Journal',
                   narration='', reference='', post=False, manual=True,
                   system_generated=False, sector=None,
                   auto_narration=None, narration_source=None):
    date = parse_date(date)
    fy = resolve_financial_year(date)
    cleaned = validate_lines(company, lines_data, manual=manual)
    voucher = Voucher(
        company=company,
        financial_year=fy,
        sector=_resolve_sector(sector),
        voucher_type=voucher_type,
        date=date,
        narration=narration or '',
        reference=reference or '',
        created_by=user,
        system_generated=system_generated,
        total_debit=sum(l['debit'] for l in cleaned),
        total_credit=sum(l['credit'] for l in cleaned),
    )
    _apply_narration_fields(voucher, user, auto_narration, narration_source)
    voucher.save()
    _write_lines(voucher, cleaned)
    if post:
        post_voucher(voucher, user=user)
    return voucher


def _write_lines(voucher, cleaned):
    voucher.lines.all().delete()
    VoucherLine.objects.bulk_create([
        VoucherLine(
            voucher=voucher,
            line_no=index,
            account=line['account'],
            cost_center=line['cost_center'],
            date=voucher.date,
            debit=line['debit'],
            credit=line['credit'],
            narration=line['narration'],
        )
        for index, line in enumerate(cleaned, start=1)
    ])


@transaction.atomic
def update_draft(voucher, date, lines_data, user=None, narration=None, reference=None,
                 sector=Ellipsis, auto_narration=None, narration_source=None):
    if voucher.status != 'Draft':
        raise ValidationError("Only draft vouchers can be edited. Cancel and re-enter a posted voucher.")
    date = parse_date(date)
    fy = resolve_financial_year(date)
    cleaned = validate_lines(voucher.company, lines_data)
    voucher.financial_year = fy
    voucher.date = date
    if narration is not None:
        voucher.narration = narration
    if reference is not None:
        voucher.reference = reference
    if sector is not Ellipsis:
        voucher.sector = _resolve_sector(sector)
    voucher.total_debit = sum(l['debit'] for l in cleaned)
    voucher.total_credit = sum(l['credit'] for l in cleaned)
    _apply_narration_fields(voucher, user, auto_narration, narration_source)
    voucher.save()
    _write_lines(voucher, cleaned)
    return voucher


@transaction.atomic
def post_voucher(voucher, user=None):
    if voucher.status != 'Draft':
        raise ValidationError(f"Voucher is already {voucher.status.lower()}.")
    # Re-read the year: it may have been closed/locked since the draft loaded.
    fy = FinancialYear.objects.get(pk=voucher.financial_year_id)
    if fy.state != 'Open':
        raise ValidationError(f"Financial year {fy_label(fy)} is {fy.state.lower()}; posting is not allowed.")
    if not (fy.start_date <= voucher.date <= fy.end_date):
        raise ValidationError("Voucher date falls outside its financial year.")
    totals = voucher.lines.aggregate(debit=Sum('debit'), credit=Sum('credit'))
    if not totals['debit'] or totals['debit'] != totals['credit']:
        raise ValidationError("Voucher is not balanced.")
    voucher.voucher_no = next_voucher_no(voucher.company, fy, voucher.voucher_type)
    voucher.status = 'Posted'
    voucher.posted_by = user
    voucher.posted_at = timezone.now()
    voucher.save(update_fields=['voucher_no', 'status', 'posted_by', 'posted_at', 'updated_at'])
    return voucher


@transaction.atomic
def cancel_voucher(voucher, user=None, reason=''):
    if voucher.status != 'Posted':
        raise ValidationError("Only posted vouchers can be cancelled (drafts can simply be deleted).")
    if FinancialYear.objects.get(pk=voucher.financial_year_id).state == 'Locked':
        raise ValidationError("The financial year is locked; the voucher cannot be cancelled.")
    voucher.status = 'Cancelled'
    voucher.cancelled_by = user
    voucher.cancelled_at = timezone.now()
    voucher.cancel_reason = (reason or '')[:255]
    voucher.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'cancel_reason', 'updated_at'])
    return voucher


# ---------------------------------------------------------- opening voucher

@transaction.atomic
def sync_opening_voucher(company, fy=None, user=None):
    """(Re)build the system Opening voucher for the financial year from the
    opening_balance fields on the chart of accounts. Replaces any previous
    system-generated Opening voucher for that year."""
    fy = fy or FinancialYear.objects.filter(is_active=True).first()
    if fy is None:
        return None
    lines = []
    accounts = ChartOfAccount.objects.filter(
        company=company, is_postable=True,
    ).exclude(opening_balance=0)
    for account in accounts:
        lines.append({
            'account': account.pk,
            'debit': account.opening_balance if account.opening_type == 'Debit' else 0,
            'credit': account.opening_balance if account.opening_type == 'Credit' else 0,
            'narration': 'Opening balance',
        })
    Voucher.objects.filter(
        company=company, financial_year=fy, voucher_type='Opening', system_generated=True,
    ).delete()
    if not lines:
        return None
    return create_voucher(
        company=company,
        date=fy.start_date,
        lines_data=lines,
        user=user,
        voucher_type='Opening',
        narration=f"Opening balances for FY {fy_label(fy)}",
        post=True,
        manual=False,
        system_generated=True,
    )


# ------------------------------------------------------------------ reports

def _posted_lines(company):
    return VoucherLine.objects.filter(voucher__company=company, voucher__status='Posted')


def account_balance(account, date_to=None):
    """Signed balance (positive = debit) from posted lines."""
    lines = _posted_lines(account.company).filter(account=account)
    if date_to:
        lines = lines.filter(date__lte=date_to)
    totals = lines.aggregate(debit=Sum('debit'), credit=Sum('credit'))
    return (totals['debit'] or Decimal('0')) - (totals['credit'] or Decimal('0'))


def account_ledger(account, date_from=None, date_to=None):
    """Ledger statement: opening, rows with running balance, closing."""
    opening = Decimal('0')
    if date_from:
        before = _posted_lines(account.company).filter(account=account, date__lt=date_from)
        totals = before.aggregate(debit=Sum('debit'), credit=Sum('credit'))
        opening = (totals['debit'] or Decimal('0')) - (totals['credit'] or Decimal('0'))
    lines = (
        _posted_lines(account.company)
        .filter(account=account)
        .select_related('voucher')
        .order_by('date', 'voucher_id', 'line_no')
    )
    if date_from:
        lines = lines.filter(date__gte=date_from)
    if date_to:
        lines = lines.filter(date__lte=date_to)

    running = opening
    rows = []
    for line in lines:
        running += (line.debit or 0) - (line.credit or 0)
        rows.append({
            'date': line.date,
            'voucher_id': line.voucher_id,
            'voucher_no': line.voucher.voucher_no,
            'voucher_type': line.voucher.voucher_type,
            'narration': line.narration or line.voucher.narration,
            'debit': line.debit,
            'credit': line.credit,
            'balance': running,
        })
    return {'opening': opening, 'rows': rows, 'closing': running}


def branch_summary_report(company, date_from=None, date_to=None):
    """Per-branch debit/credit/net movement from posted lines, rolled up via
    each voucher's Office (Voucher.sector) through the Sector -> Branch
    mapping (Inventory > Master > Office Mapping). Vouchers with no Office,
    or whose Office isn't linked to a Branch yet, land under 'Unmapped' —
    the report doubles as a nudge to finish that mapping."""
    from broiler.models import Branch
    from inventory.models import Mapping

    lines = _posted_lines(company)
    if date_from:
        lines = lines.filter(date__gte=date_from)
    if date_to:
        lines = lines.filter(date__lte=date_to)

    by_office = lines.values('voucher__sector_id').annotate(debit=Sum('debit'), credit=Sum('credit'))

    office_to_branch = dict(
        Mapping.objects.filter(type=Mapping.TYPE_SECTOR_BRANCH, to_id__isnull=False)
        .values_list('from_id', 'to_id')
    )
    branch_names = dict(Branch.objects.values_list('id', 'branch_name'))

    buckets = {}
    for entry in by_office:
        office_id = entry['voucher__sector_id']
        debit = entry['debit'] or Decimal('0')
        credit = entry['credit'] or Decimal('0')
        if not (debit or credit):
            continue
        branch_id = office_to_branch.get(office_id) if office_id else None
        bucket = buckets.setdefault(branch_id, {'debit': Decimal('0'), 'credit': Decimal('0')})
        bucket['debit'] += debit
        bucket['credit'] += credit

    rows = []
    totals = {'debit': Decimal('0'), 'credit': Decimal('0'), 'net': Decimal('0')}
    for branch_id, amounts in buckets.items():
        net = amounts['debit'] - amounts['credit']
        rows.append({
            'branch_id': branch_id,
            'branch_name': branch_names.get(branch_id, 'Unmapped') if branch_id else 'Unmapped',
            'debit': amounts['debit'],
            'credit': amounts['credit'],
            'net': net,
        })
        totals['debit'] += amounts['debit']
        totals['credit'] += amounts['credit']
        totals['net'] += net
    rows.sort(key=lambda r: (r['branch_name'] == 'Unmapped', r['branch_name']))
    return {'rows': rows, 'totals': totals}


def cost_center_report(company, date_from=None, date_to=None):
    """Per-cost-center debit/credit/net movement from posted lines, for the
    Cost Center Report (Account > Reports > Cost Center). Lines with no
    cost center tagged roll up under an 'Unassigned' row, so the report also
    surfaces how much posted spend isn't tagged yet."""
    lines = _posted_lines(company)
    if date_from:
        lines = lines.filter(date__gte=date_from)
    if date_to:
        lines = lines.filter(date__lte=date_to)

    aggregated = lines.values(
        'cost_center_id', 'cost_center__code', 'cost_center__name', 'cost_center__kind__name',
    ).annotate(debit=Sum('debit'), credit=Sum('credit')).order_by('cost_center__code')

    rows = []
    totals = {'debit': Decimal('0'), 'credit': Decimal('0'), 'net': Decimal('0')}
    for entry in aggregated:
        debit = entry['debit'] or Decimal('0')
        credit = entry['credit'] or Decimal('0')
        if not (debit or credit):
            continue
        rows.append({
            'cost_center_id': entry['cost_center_id'],
            'code': entry['cost_center__code'] or '—',
            'name': entry['cost_center__name'] or 'Unassigned',
            'kind': entry['cost_center__kind__name'] or '',
            'debit': debit,
            'credit': credit,
            'net': debit - credit,
        })
        totals['debit'] += debit
        totals['credit'] += credit
        totals['net'] += debit - credit
    return {'rows': rows, 'totals': totals}


def trial_balance(company, date_from=None, date_to=None):
    """Per-account opening/period/closing figures from posted lines."""
    from django.db.models import Q

    lines = _posted_lines(company)
    if date_to:
        lines = lines.filter(date__lte=date_to)

    annotations = {
        'period_debit': Sum('debit', filter=Q(date__gte=date_from)) if date_from else Sum('debit'),
        'period_credit': Sum('credit', filter=Q(date__gte=date_from)) if date_from else Sum('credit'),
    }
    if date_from:
        annotations['opening'] = Sum(
            F('debit') - F('credit'),
            filter=Q(date__lt=date_from),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )

    aggregated = lines.values(
        'account_id', 'account__code', 'account__description',
        'account__account_type__name', 'account__type',
    ).annotate(**annotations).order_by('account__code')

    rows = []
    totals = {'opening_debit': Decimal('0'), 'opening_credit': Decimal('0'),
              'debit': Decimal('0'), 'credit': Decimal('0'),
              'closing_debit': Decimal('0'), 'closing_credit': Decimal('0')}
    for entry in aggregated:
        opening = entry.get('opening') or Decimal('0')
        debit = entry['period_debit'] or Decimal('0')
        credit = entry['period_credit'] or Decimal('0')
        closing = opening + debit - credit
        if not (opening or debit or credit):
            continue
        rows.append({
            'account_id': entry['account_id'],
            'code': entry['account__code'],
            'description': entry['account__description'],
            'account_type': entry['account__account_type__name'] or entry['account__type'],
            'opening_debit': opening if opening > 0 else Decimal('0'),
            'opening_credit': -opening if opening < 0 else Decimal('0'),
            'debit': debit,
            'credit': credit,
            'closing_debit': closing if closing > 0 else Decimal('0'),
            'closing_credit': -closing if closing < 0 else Decimal('0'),
        })
        totals['opening_debit'] += rows[-1]['opening_debit']
        totals['opening_credit'] += rows[-1]['opening_credit']
        totals['debit'] += debit
        totals['credit'] += credit
        totals['closing_debit'] += rows[-1]['closing_debit']
        totals['closing_credit'] += rows[-1]['closing_credit']
    return {'rows': rows, 'totals': totals}


# ------------------------------------------------------- P&L / balance sheet

def _grouped_movement(company, date_from, date_to, report):
    """Per-account net movement for accounts of the given statement
    (``'PL'`` or ``'BS'``), signed positive on the account's normal-balance
    side (e.g. an Asset with more debits, or Income with more credits, is
    positive). Zero-movement accounts are omitted.
    """
    lines = _posted_lines(company).filter(account__account_type__report=report)
    if date_from:
        lines = lines.filter(date__gte=date_from)
    if date_to:
        lines = lines.filter(date__lte=date_to)

    aggregated = lines.values(
        'account_id', 'account__code', 'account__description',
        'account__account_type__code', 'account__account_type__name',
        'account__account_type__normal_balance', 'account__account_group__name',
    ).annotate(debit=Sum('debit'), credit=Sum('credit')).order_by('account__code')

    rows = []
    for entry in aggregated:
        debit = entry['debit'] or Decimal('0')
        credit = entry['credit'] or Decimal('0')
        if not (debit or credit):
            continue
        is_debit_normal = entry['account__account_type__normal_balance'] == 'Debit'
        amount = (debit - credit) if is_debit_normal else (credit - debit)
        rows.append({
            'account_id': entry['account_id'],
            'code': entry['account__code'],
            'description': entry['account__description'],
            'type_code': entry['account__account_type__code'],
            'type_name': entry['account__account_type__name'],
            'group': entry['account__account_group__name'],
            'amount': amount,
        })
    return rows


def profit_and_loss(company, date_from=None, date_to=None):
    """Income/COGS/Expense movement for a period -> gross and net profit.

    Cumulative since inception when ``date_from`` is omitted (no year-end
    closing exists yet to reset P&L accounts to zero between years).
    """
    rows = _grouped_movement(company, date_from, date_to, report='PL')
    income = [r for r in rows if r['type_code'] == 'INCOME']
    cogs = [r for r in rows if r['type_code'] == 'COGS']
    expense = [r for r in rows if r['type_code'] == 'EXPENSE']
    total_income = sum((r['amount'] for r in income), Decimal('0'))
    total_cogs = sum((r['amount'] for r in cogs), Decimal('0'))
    total_expense = sum((r['amount'] for r in expense), Decimal('0'))
    gross_profit = total_income - total_cogs
    net_profit = gross_profit - total_expense
    return {
        'income': income, 'cogs': cogs, 'expense': expense,
        'total_income': total_income, 'total_cogs': total_cogs,
        'gross_profit': gross_profit, 'total_expense': total_expense,
        'net_profit': net_profit,
    }


def balance_sheet(company, date_upto=None):
    """Asset/Liability/Equity position as of a date, with current (unclosed)
    P&L folded into Equity as 'Current Earnings' so it always balances -
    by double-entry construction, Assets == Liabilities + Equity exactly.
    """
    rows = _grouped_movement(company, date_from=None, date_to=date_upto, report='BS')
    assets = [r for r in rows if r['type_code'] == 'ASSET']
    liabilities = [r for r in rows if r['type_code'] == 'LIABILITY']
    equity = [r for r in rows if r['type_code'] == 'EQUITY']

    total_assets = sum((r['amount'] for r in assets), Decimal('0'))
    total_liabilities = sum((r['amount'] for r in liabilities), Decimal('0'))
    total_equity_recorded = sum((r['amount'] for r in equity), Decimal('0'))

    current_earnings = profit_and_loss(company, date_from=None, date_to=date_upto)['net_profit']
    total_equity = total_equity_recorded + current_earnings
    total_liabilities_and_equity = total_liabilities + total_equity

    return {
        'assets': assets, 'liabilities': liabilities, 'equity': equity,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity_recorded': total_equity_recorded,
        'current_earnings': current_earnings,
        'total_equity': total_equity,
        'total_liabilities_and_equity': total_liabilities_and_equity,
        'balanced': total_assets == total_liabilities_and_equity,
    }
