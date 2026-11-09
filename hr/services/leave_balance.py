"""Leave entitlement against leave taken, per employee per calendar year.

A balance only means something for a type that grants days, so types with
no ``annual_entitlement`` are left out — they are still usable for
classifying a request (and for telling payroll whether it is paid), they
just have nothing to count down from.

Days taken are weighted by how much of a day the request covers: a
first-half request consumes half a day of entitlement, not a whole one.
That weighting lives on ``EmployeeLeave.leave_type`` (Full Day / First
Half / Second Half), which is a different field from
``leave_category`` — the latter is the type this balance is measured
against.
"""
from decimal import Decimal

from hr.models import LeaveSelectedDate, LeaveType

#: How much of a day each request shape consumes.
DAY_WEIGHT = {
    "Full Day": Decimal("1.0"),
    "First Half": Decimal("0.5"),
    "Second Half": Decimal("0.5"),
}


def days_taken(employee, year, leave_type):
    """Approved days of *leave_type* this employee used in *year*."""
    rows = (
        LeaveSelectedDate.objects
        .filter(
            leave_request__employee=employee,
            leave_request__status="Approved",
            leave_request__leave_category=leave_type,
            date__year=year,
        )
        .values_list("leave_request__leave_type", flat=True)
    )
    return sum((DAY_WEIGHT.get(shape, Decimal("1.0")) for shape in rows),
               Decimal("0"))


def leave_balance(employee, year):
    """Entitled / taken / balance for every type that grants days.

    The balance is allowed to go negative and is reported as it is: an
    employee who has over-drawn a type is exactly what somebody looking at
    this screen needs to see, and clamping it at zero would hide it.
    """
    balances = []
    for leave_type in (LeaveType.objects
                       .filter(is_active=True, annual_entitlement__gt=0)
                       .order_by("name")):
        entitled = Decimal(str(leave_type.annual_entitlement))
        taken = days_taken(employee, year, leave_type)
        balances.append({
            "leave_type": leave_type,
            "name": leave_type.name,
            "code": leave_type.code,
            "is_paid": leave_type.is_paid,
            "entitled": entitled,
            "taken": taken,
            "balance": entitled - taken,
        })
    return balances
