"""Seed system account types/groups and backfill existing chart-of-account
rows into the new engine schema:

- every pre-existing account is assigned to the default company (pk=1),
- its legacy string ``type`` is linked to the matching AccountType row,
- it stays a postable leaf (level 0, path = own code), which is exactly how
  the flat legacy chart behaved.

Reversal only clears the seeded system rows; account data is untouched.
"""
from django.db import migrations

LEGACY_TYPE_TO_CODE = {
    'Asset': 'ASSET',
    'Liability': 'LIABILITY',
    'Equity': 'EQUITY',
    'Revenue': 'INCOME',
    'Income': 'INCOME',
    'Expense': 'EXPENSE',
    'COGS': 'COGS',
}


def seed_and_backfill(apps, schema_editor):
    from account.coa_seed import ACCOUNT_TYPES, ACCOUNT_GROUPS

    AccountType = apps.get_model('account', 'AccountType')
    AccountGroup = apps.get_model('account', 'AccountGroup')
    ChartOfAccount = apps.get_model('account', 'ChartOfAccount')
    CompanyProfile = apps.get_model('account', 'CompanyProfile')

    for code, name, balance, report, start, end, sort in ACCOUNT_TYPES:
        AccountType.objects.update_or_create(
            code=code,
            defaults={
                'name': name,
                'normal_balance': balance,
                'report': report,
                'code_range_start': start,
                'code_range_end': end,
                'is_system': True,
                'sort_order': sort,
            },
        )

    types = {t.code: t for t in AccountType.objects.all()}
    for name, type_code in ACCOUNT_GROUPS:
        AccountGroup.objects.update_or_create(
            name=name,
            defaults={'account_type': types[type_code], 'is_system': True},
        )

    if ChartOfAccount.objects.exists():
        company, _ = CompanyProfile.objects.get_or_create(pk=1, defaults={'name': 'Company Name'})
        for account in ChartOfAccount.objects.filter(company__isnull=True):
            account.company = company
            account.account_type = types.get(LEGACY_TYPE_TO_CODE.get(account.type))
            account.path = account.code
            account.level = 0
            account.save(update_fields=['company', 'account_type', 'path', 'level'])


def unseed(apps, schema_editor):
    AccountGroup = apps.get_model('account', 'AccountGroup')
    AccountType = apps.get_model('account', 'AccountType')
    AccountGroup.objects.filter(is_system=True).delete()
    AccountType.objects.filter(is_system=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0006_accountauditlog_accountgroup_accounttype_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_and_backfill, unseed),
    ]
