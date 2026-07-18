"""Backfill system_role anchors for expense/income ledgers the auto-narration
engine keys off (Rent, Electricity, Fuel, Freight, Interest).

These accounts already exist (created before this change added their roles to
account/coa_seed.py) with system_role blank; both already-generated company
chart-of-accounts and already-seeded CoATemplate blueprints are updated here so
new companies don't need `seed_coa_templates --rebuild` to pick this up.
Idempotent: only touches rows whose system_role is still blank, matched by the
code the base seed tree assigns to each (none of these codes are reused for a
different account by any industry overlay).

Reversal clears the same roles back to blank.
"""
from django.db import migrations
from django.db.models import Q

CODE_ROLES = {
    "420002": "INTEREST_INCOME",
    "510003": "FREIGHT_INWARD_EXPENSE",
    "610002": "RENT_EXPENSE",
    "620002": "FREIGHT_OUTWARD_EXPENSE",
    "630002": "INTEREST_EXPENSE",
    "670001": "ELECTRICITY_EXPENSE",
    "670003": "FUEL_EXPENSE",
}


def backfill(apps, schema_editor):
    ChartOfAccount = apps.get_model('account', 'ChartOfAccount')
    CoATemplateAccount = apps.get_model('account', 'CoATemplateAccount')
    blank = Q(system_role__isnull=True) | Q(system_role='')
    for code, role in CODE_ROLES.items():
        ChartOfAccount.objects.filter(blank, code=code).update(system_role=role)
        CoATemplateAccount.objects.filter(blank, account_code=code).update(system_role=role)


def unbackfill(apps, schema_editor):
    ChartOfAccount = apps.get_model('account', 'ChartOfAccount')
    CoATemplateAccount = apps.get_model('account', 'CoATemplateAccount')
    roles = list(CODE_ROLES.values())
    ChartOfAccount.objects.filter(system_role__in=roles).update(system_role='')
    CoATemplateAccount.objects.filter(system_role__in=roles).update(system_role='')


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0011_voucher_auto_narration_voucher_narration_edited_at_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
