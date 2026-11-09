"""Seed the four leave types every payroll needs to tell paid from unpaid.

Idempotent on name, so running it against a database that already has them
changes nothing. Existing EmployeeLeave rows are deliberately left with a
null ``leave_category``: they were granted before the distinction existed
and payroll treats a missing category as paid, which is the footing they
were approved on.
"""
from django.db import migrations

# (name, is_paid, annual_entitlement)
STANDARD_TYPES = [
    ("Casual Leave", True, 12),
    ("Sick Leave", True, 12),
    ("Earned Leave", True, 15),
    ("Leave Without Pay", False, 0),
]


def seed_leave_types(apps, schema_editor):
    LeaveType = apps.get_model("hr", "LeaveType")
    # The model's own save() mints the code, and historical models do not
    # carry it, so the serial is worked out here instead.
    existing = list(LeaveType.objects.values_list("code", flat=True))
    next_num = 0
    for code in existing:
        if code and code.startswith("LT-"):
            try:
                next_num = max(next_num, int(code[3:]))
            except ValueError:
                pass

    for name, is_paid, entitlement in STANDARD_TYPES:
        if LeaveType.objects.filter(name=name).exists():
            continue
        next_num += 1
        LeaveType.objects.create(
            code=f"LT-{next_num:04d}",
            name=name,
            is_paid=is_paid,
            annual_entitlement=entitlement,
            is_active=True,
        )


def noop(apps, schema_editor):
    """Nothing to undo: the types may be in use by the time this reverses,
    and deleting them would be refused by the PROTECT on leave_category."""


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0034_leavetype_employeeleave_leave_category"),
    ]

    operations = [
        migrations.RunPython(seed_leave_types, noop),
    ]
