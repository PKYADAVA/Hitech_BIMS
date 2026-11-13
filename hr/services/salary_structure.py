"""Reading an employee's salary structure, and what it earns in a month.

An employee with no structure rows is paid exactly as they were before
structures existed: ``Employee.salary`` spread over ``daily_wage``. That is
not a fallback bolted on, it is the contract — most of the payroll in this
system predates components, and a structure nobody has filled in must not
change anybody's pay. Every function here says so explicitly rather than
leaving it to a ``None`` wandering through the arithmetic.

Components are earned pro-rata for the days worked, the same way the flat
salary already is: a half-attended month pays half. ``earned_ratio`` is the
caller's — payroll owns what counts as a day worked, this owns what a full
month is worth.

Statutory deductions (PF/ESI/TDS) are deliberately absent. They need
chart-of-accounts anchors this system does not have and rates that belong
in law, so payroll stops at what the employer has agreed to pay.
"""
from decimal import Decimal

from hr.models import EmployeeSalaryStructure

ZERO = Decimal("0")


def _dec(value):
    return Decimal(str(value or 0))


def structure_for(employee, on_date):
    """The structure rows in force for *employee* on *on_date*.

    One row per component — the latest ``effective_from`` on or before the
    date, so a raise dated this month does not restate last month.
    """
    rows = (EmployeeSalaryStructure.objects
            .filter(employee=employee, is_active=True,
                    effective_from__lte=on_date)
            .select_related("component")
            .order_by("component_id", "-effective_from", "-id"))

    latest = {}
    for row in rows:
        # Ordered newest-first within each component, so the first one seen
        # is the one in force and the rest are its history.
        if row.component_id not in latest and row.component.is_active:
            latest[row.component_id] = row
    return list(latest.values())


def has_structure(employee, on_date):
    """Whether this employee is paid by components at all on this date."""
    return bool(structure_for(employee, on_date))


def basic_amount(rows):
    """The Basic the percentage components are a percentage of.

    Zero when there is no Basic row: a percentage of nothing is nothing,
    which is the honest answer rather than silently treating some other
    earning as the base.
    """
    for row in rows:
        if row.component.is_basic:
            return _dec(row.amount)
    return ZERO


def full_month_breakdown(employee, on_date):
    """What each component is worth for a *whole* month, before pro-rating.

    Returns ``(earnings, deductions)`` as lists of
    ``{"component", "name", "amount"}``. Percent-of-Basic components are
    resolved against the Basic row here, so callers never see a percentage
    where they expect rupees.
    """
    rows = structure_for(employee, on_date)
    basic = basic_amount(rows)

    earnings, deductions = [], []
    for row in rows:
        if row.component.calculation == "Percent of Basic":
            amount = (basic * _dec(row.amount)) / Decimal("100")
        else:
            amount = _dec(row.amount)
        entry = {"component": row.component, "name": row.component.name,
                 "amount": amount}
        if row.component.component_type == "Deduction":
            deductions.append(entry)
        else:
            earnings.append(entry)
    return earnings, deductions


def full_month_gross(employee, on_date):
    """Total earnings for a whole month under the structure.

    ``Employee.salary`` when there is no structure — the figure payroll
    has always called gross.
    """
    if not has_structure(employee, on_date):
        return _dec(employee.salary)
    earnings, _ = full_month_breakdown(employee, on_date)
    return sum((e["amount"] for e in earnings), ZERO)


def compute_gross(employee, on_date, earned_ratio):
    """What the structure earns for a part-worked month.

    *earned_ratio* is days worked over days payable, as payroll counts
    them. An employee with no structure is paid the flat way instead, and
    the caller is told which happened so it does not have to guess:

        (amount, used_structure)
    """
    ratio = _dec(earned_ratio)
    if not has_structure(employee, on_date):
        # Untouched: the flat salary, pro-rated exactly as before.
        return _dec(employee.salary) * ratio, False
    return full_month_gross(employee, on_date) * ratio, True


def breakdown_for_month(employee, on_date, earned_ratio):
    """Per-component earnings and deductions for a part-worked month.

    What a payslip needs. Empty lists when there is no structure — there
    is nothing to break down, and the flat salary is the whole story.
    """
    if not has_structure(employee, on_date):
        return [], []
    ratio = _dec(earned_ratio)
    earnings, deductions = full_month_breakdown(employee, on_date)
    for entry in earnings + deductions:
        entry["amount"] = entry["amount"] * ratio
    return earnings, deductions
