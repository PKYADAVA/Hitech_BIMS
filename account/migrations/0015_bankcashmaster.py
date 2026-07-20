import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


def migrate_bank_and_cash_rows(apps, schema_editor):
    """Copy every BankCode/CashCode row into the new unified BankCashMaster,
    then re-point their auto-generated COA ledger (ChartOfAccount.source_*)
    at the new row so existing ledger links keep resolving."""
    ContentType = apps.get_model("contenttypes", "ContentType")
    ChartOfAccount = apps.get_model("account", "ChartOfAccount")
    BankCode = apps.get_model("account", "BankCode")
    CashCode = apps.get_model("account", "CashCode")
    BankCashMaster = apps.get_model("account", "BankCashMaster")

    bank_ct, _ = ContentType.objects.get_or_create(app_label="account", model="bankcode")
    cash_ct, _ = ContentType.objects.get_or_create(app_label="account", model="cashcode")
    new_ct, _ = ContentType.objects.get_or_create(app_label="account", model="bankcashmaster")

    for bank in BankCode.objects.all():
        new_row = BankCashMaster.objects.create(
            is_cash=False, code=bank.bank_code, name=bank.bank_name,
            sector_id=bank.sector_id, micr=bank.micr, address=bank.address,
            email=bank.email, phone=bank.phone, fax=bank.fax,
            contact_person=bank.contact_person,
        )
        ChartOfAccount.objects.filter(
            source_content_type=bank_ct, source_object_id=bank.id
        ).update(source_content_type=new_ct, source_object_id=new_row.id)

    for cash in CashCode.objects.all():
        new_row = BankCashMaster.objects.create(
            is_cash=True, code=cash.cash_code, name=cash.cash_name,
            sector_id=cash.sector_id, address=cash.address,
            phone=cash.phone, contact_person=cash.contact_person,
        )
        ChartOfAccount.objects.filter(
            source_content_type=cash_ct, source_object_id=cash.id
        ).update(source_content_type=new_ct, source_object_id=new_row.id)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('account', '0014_require_bank_cash_sector'),
    ]

    operations = [
        migrations.CreateModel(
            name='BankCashMaster',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(blank=True, editable=False, help_text='Auto-generated code, e.g. BANK-0001 / CASH-0001', max_length=20, unique=True)),
                ('is_cash', models.BooleanField(default=False, help_text='Tick if this is a Cash location; leave unticked for a Bank account')),
                ('name', models.CharField(help_text='Name of the bank account / cash location', max_length=255)),
                ('micr', models.CharField(blank=True, help_text='MICR code (banks only)', max_length=15, null=True)),
                ('address', models.TextField(blank=True, help_text='Address', null=True)),
                ('email', models.EmailField(blank=True, help_text='Email address', max_length=254, null=True)),
                ('phone', models.CharField(blank=True, help_text='Phone number', max_length=20, null=True, validators=[django.core.validators.RegexValidator(message="Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.", regex='^\\+?1?\\d{9,15}$')])),
                ('fax', models.CharField(blank=True, help_text='Fax number (banks only)', max_length=20, null=True)),
                ('contact_person', models.CharField(blank=True, help_text='Contact person', max_length=100, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, help_text='Record created at')),
                ('updated_at', models.DateTimeField(auto_now=True, help_text='Last updated at')),
                ('sector', models.ForeignKey(help_text='Office this bank/cash record is mapped to', on_delete=django.db.models.deletion.PROTECT, related_name='bank_cash_masters', to='inventory.warehouse')),
            ],
            options={
                'verbose_name': 'Bank / Cash Master',
                'verbose_name_plural': 'Bank / Cash Masters',
                'ordering': ['name'],
                'indexes': [
                    models.Index(fields=['code'], name='account_ban_code_263dad_idx'),
                    models.Index(fields=['name'], name='account_ban_name_09c660_idx'),
                ],
            },
        ),
        migrations.RunPython(migrate_bank_and_cash_rows, noop),
        migrations.DeleteModel(name='BankCode'),
        migrations.DeleteModel(name='CashCode'),
    ]
