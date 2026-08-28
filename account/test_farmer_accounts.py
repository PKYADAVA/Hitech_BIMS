"""The farmer side of the chart of accounts.

Phase one of posting growing charges: the accounts a settlement and a payment
will need, and a ledger per farmer beneath the control group. Nothing posts
yet — this is only the shape of the chart.
"""
from django.core.management import call_command
from django.test import TestCase

from account.coa_seed import seed_coa_templates
from account.models import ChartOfAccount, CoATemplate, CompanyProfile
from account.services import CoAGeneratorService
from broiler.models import Farmer


class FarmerChartTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_coa_templates()
        cls.company = CompanyProfile.get_solo()
        cls.template = CoATemplate.objects.get(industry="Poultry")

    def generate(self, **options):
        return CoAGeneratorService(self.company, self.template,
                                   options=options or None).generate()

    def account(self, role):
        return ChartOfAccount.objects.filter(company=self.company,
                                             system_role=role).first()


class FarmerAccountsTests(FarmerChartTestCase):
    def test_a_generated_chart_has_somewhere_to_book_a_growing_charge(self):
        """The expense it is charged to, and the liability it is owed under."""
        self.generate()
        expense = self.account("GROWING_CHARGES")
        payable = self.account("FARMER_PAYABLE")
        self.assertIsNotNone(expense, "Growing Charges missing from the chart")
        self.assertIsNotNone(payable, "Farmer Payable missing from the chart")
        self.assertEqual(expense.account_type.code, "EXPENSE")
        self.assertEqual(payable.account_type.code, "LIABILITY")

    def test_growing_charges_sits_with_the_other_farm_costs(self):
        self.generate()
        self.assertEqual(self.account("GROWING_CHARGES").parent.system_role,
                         "FARM_EXPENSES")

    def test_farmer_payable_is_a_group_that_holds_ledgers_not_a_postable_account(self):
        """Money is owed to a named farmer, never to "Farmer Payable" itself."""
        self.generate()
        payable = self.account("FARMER_PAYABLE")
        self.assertTrue(payable.is_group)
        self.assertFalse(payable.is_postable)

    def test_the_control_group_survives_a_chart_without_the_poultry_overlay(self):
        """It is an anchor under Current Liabilities, not part of the farm
        subtree, so a company generated on the general template still has
        somewhere to owe a farmer money."""
        template = CoATemplate.objects.get(industry="General")
        CoAGeneratorService(self.company, template).generate()
        self.assertIsNotNone(self.account("FARMER_PAYABLE"))


class FarmerLedgerTests(FarmerChartTestCase):
    def test_a_farmer_gets_a_ledger_under_the_control_group(self):
        self.generate()
        payable = self.account("FARMER_PAYABLE")
        farmer = Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        ledger = ChartOfAccount.objects.get(company=self.company, parent=payable,
                                            description="Abhishek Kumar Singh")
        self.assertTrue(ledger.is_postable)
        self.assertEqual(ledger.source, farmer)

    def test_a_rename_moves_the_ledger_rather_than_leaving_two(self):
        self.generate()
        payable = self.account("FARMER_PAYABLE")
        farmer = Farmer.objects.create(farmer_name="Ram Prasad")
        farmer.farmer_name = "Ram Prasad Yadav"
        farmer.save()
        ledgers = ChartOfAccount.objects.filter(company=self.company, parent=payable)
        self.assertEqual(ledgers.count(), 1)
        self.assertEqual(ledgers.get().description, "Ram Prasad Yadav")

    def test_a_farmer_added_before_the_chart_exists_does_not_break_the_save(self):
        """Master data must never fail because of ledger bookkeeping — the
        ledger appears on the next save once the chart is there."""
        farmer = Farmer.objects.create(farmer_name="Early Bird")
        self.generate()
        farmer.save()
        payable = self.account("FARMER_PAYABLE")
        self.assertTrue(ChartOfAccount.objects.filter(
            company=self.company, parent=payable, description="Early Bird").exists())


class BackfillCommandTests(FarmerChartTestCase):
    """The chart in production was generated before these accounts existed, and
    the generator only runs once."""

    def _strip(self):
        """A chart as it looked before this work: no farmer accounts."""
        self.generate()
        ChartOfAccount.objects.filter(
            company=self.company,
            system_role__in=["FARMER_PAYABLE", "GROWING_CHARGES"]).delete()

    def test_the_backfill_adds_both_accounts_to_an_existing_chart(self):
        self._strip()
        Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        call_command("backfill_farmer_accounts", verbosity=0)
        self.assertIsNotNone(self.account("FARMER_PAYABLE"))
        self.assertIsNotNone(self.account("GROWING_CHARGES"))

    def test_the_backfill_gives_existing_farmers_their_ledgers(self):
        """Farmers created before the control group existed have no ledger, and
        nothing would ever create one for them without this."""
        self._strip()
        Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        call_command("backfill_farmer_accounts", verbosity=0)
        payable = self.account("FARMER_PAYABLE")
        self.assertTrue(ChartOfAccount.objects.filter(
            company=self.company, parent=payable,
            description="Abhishek Kumar Singh").exists())

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self._strip()
        Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        call_command("backfill_farmer_accounts", verbosity=0)
        before = ChartOfAccount.objects.filter(company=self.company).count()
        call_command("backfill_farmer_accounts", verbosity=0)
        self.assertEqual(ChartOfAccount.objects.filter(company=self.company).count(),
                         before)

    def test_a_dry_run_writes_nothing(self):
        self._strip()
        Farmer.objects.create(farmer_name="Abhishek Kumar Singh")
        before = ChartOfAccount.objects.filter(company=self.company).count()
        call_command("backfill_farmer_accounts", "--dry-run", verbosity=0)
        self.assertEqual(ChartOfAccount.objects.filter(company=self.company).count(),
                         before)
        self.assertIsNone(self.account("FARMER_PAYABLE"))
