"""Add the farmer accounts to charts that were generated before they existed.

Three accounts and a ledger per farmer:

    215000  Farmer Payable    control group, one ledger per farmer beneath it
    640006  Growing Charges   the expense a settlement raises
    630001  Bank Charges      already there, but seeded without a system role,
                              so posting could not find it — the role is
                              stamped onto that account rather than a second
                              one being created beside it

A company whose chart was generated before these were seeded has neither, and
the generator only runs once. This brings an existing chart up to date without
regenerating it, which would disturb accounts that already carry balances.

Idempotent: accounts are matched by system role, ledgers by their source link,
so running it twice changes nothing the second time. Safe to run again after
adding farmers.

    python manage.py backfill_farmer_accounts --dry-run
    python manage.py backfill_farmer_accounts
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from account.models import AccountType, ChartOfAccount, CompanyProfile
from account.services.auto_ledger import sync_ledger
from account.services.code_generator import AccountCodeGenerator


class Command(BaseCommand):
    help = "Create the Farmer Payable and Growing Charges accounts, and a ledger per farmer."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Report what would change without writing anything.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        companies = CompanyProfile.objects.all()
        if not companies:
            self.stdout.write("No companies. Nothing to do.")
            return

        for company in companies:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{company.name}"))
            if not ChartOfAccount.objects.filter(company=company).exists():
                self.stdout.write("  no chart generated yet — the generator will "
                                  "include these accounts itself. Skipped.")
                continue
            with transaction.atomic():
                payable = self._ensure(company, "FARMER_PAYABLE", "Farmer Payable",
                                       "LIABILITY", ["CURRENT_LIABILITIES"],
                                       is_group=True, dry=dry)
                self._ensure(company, "GROWING_CHARGES", "Growing Charges", "EXPENSE",
                             # Beside the other farm costs where that subtree
                             # exists; under Expenses itself where it does not.
                             ["FARM_EXPENSES", "MANUFACTURING_EXPENSES", "EXPENSES_ROOT"],
                             is_group=False, dry=dry)
                # Bank Charges is usually already there, seeded before system
                # roles were put on it. Adopt that account rather than creating
                # a second one with the same name.
                self._ensure(company, "BANK_CHARGES", "Bank Charges", "EXPENSE",
                             ["FINANCIAL_EXPENSES", "EXPENSES_ROOT"],
                             is_group=False, dry=dry, adopt="Bank Charges")
                if payable is not None:
                    self._ledgers(company, dry)
                if dry:
                    transaction.set_rollback(True)

        if dry:
            self.stdout.write(self.style.WARNING("\nDry run — nothing was written."))

    def _ensure(self, company, role, name, type_code, parent_roles, is_group, dry,
                adopt=None):
        existing = ChartOfAccount.objects.filter(company=company, system_role=role).first()
        if existing:
            self.stdout.write(f"  {role}: already {existing.code} {existing.description}")
            return existing

        if adopt:
            # An account that has always been there but was seeded without a
            # role. Stamping the role on it is safer than adding a second
            # account with the same name and splitting its history.
            match = ChartOfAccount.objects.filter(
                company=company, description__iexact=adopt,
                system_role__isnull=True).first()
            if match is None:
                match = ChartOfAccount.objects.filter(
                    company=company, description__iexact=adopt,
                    system_role="").first()
            if match:
                self.stdout.write(self.style.SUCCESS(
                    f"  {role}: adopting existing {match.code} {match.description}"))
                if not dry:
                    match.system_role = role
                    match.save(update_fields=["system_role"])
                return match

        parent = None
        for parent_role in parent_roles:
            parent = ChartOfAccount.objects.filter(company=company,
                                                   system_role=parent_role).first()
            if parent:
                break
        if parent is None:
            self.stdout.write(self.style.ERROR(
                f"  {role}: no parent found among {', '.join(parent_roles)} — skipped"))
            return None

        account_type = AccountType.objects.filter(code=type_code).first()
        if account_type is None:
            self.stdout.write(self.style.ERROR(f"  {role}: account type {type_code} missing"))
            return None

        code = AccountCodeGenerator(company).next_code(
            parent=parent, account_type=account_type, is_group=is_group)
        self.stdout.write(self.style.SUCCESS(
            f"  {role}: creating {code} {name} under {parent.code} {parent.description}"))
        if dry:
            return parent            # truthy, so the ledger pass still reports

        account = ChartOfAccount(
            company=company, parent=parent, code=code, description=name,
            account_type=account_type, currency=parent.currency,
            is_group=is_group, is_postable=not is_group,
            system_generated=True, system_role=role,
        )
        account.save()
        return account

    def _ledgers(self, company, dry):
        """One ledger per farmer, the way suppliers and customers already get one."""
        from broiler.models import Farmer

        farmers = Farmer.objects.all()
        if not farmers:
            self.stdout.write("  no farmers yet — ledgers appear as they are added")
            return
        made = 0
        for farmer in farmers:
            if dry:
                continue
            # sync_ledger is idempotent and links back to the farmer, so a
            # rename propagates and a second run creates nothing.
            made += len(sync_ledger(farmer, farmer.farmer_name, ["FARMER_PAYABLE"],
                                    company=company))
        if dry:
            self.stdout.write(f"  would sync ledgers for {len(farmers)} farmer(s)")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"  ledgers synced for {len(farmers)} farmer(s)"))
