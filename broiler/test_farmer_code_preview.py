"""The preview that shows what the farmer-code backfill would issue.

The codes are permanent once people start quoting them, so the numbering is
worth checking against live data before the migration runs. This covers what
the preview reports, including the cases where a farm code cannot vouch for a
farmer's place in the order.
"""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor


class FarmerCodePreviewTests(TestCase):

    def setUp(self):
        self.now = timezone.now()
        region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="A. Pal")

    def farmer(self, name, days_ago):
        farmer = Farmer.objects.create(farmer_name=name)
        # auto_now_add fills created_at, so an age has to be written afterwards.
        Farmer.objects.filter(pk=farmer.pk).update(created_at=self.now - timedelta(days=days_ago))
        return Farmer.objects.get(pk=farmer.pk)

    def farm(self, farmer, name, days_ago, code=None):
        farm = BroilerFarm.objects.create(
            farm_name=name, branch=self.branch, supervisor=self.supervisor, farmer=farmer,
            region="East", line="Baskhari", farm_capacity=1000)
        updates = {"created_at": self.now - timedelta(days=days_ago)}
        if code:
            updates["farm_code"] = code
        BroilerFarm.objects.filter(pk=farm.pk).update(**updates)
        return farm

    def preview(self, *args):
        out = StringIO()
        call_command("preview_farmer_codes", *args, stdout=out)
        return out.getvalue()

    def test_the_oldest_farmer_would_be_first(self):
        self.farmer("Newest", days_ago=1)
        self.farmer("Oldest", days_ago=900)
        self.farmer("Middle", days_ago=400)
        report = self.preview()
        self.assertIn("FRM-0001 would go to Oldest", report)
        # The whole run counts up by age, not by name.
        order = [line.split()[2] for line in report.splitlines() if line.startswith("FRM-")]
        self.assertEqual(order, ["Oldest", "Middle", "Newest"])

    def test_a_farmer_with_no_farm_is_counted(self):
        self.farmer("Farmless", days_ago=10)
        self.assertIn("1 have no farm", self.preview())

    def test_an_older_code_format_is_called_out(self):
        farmer = self.farmer("Legacy", days_ago=10)
        self.farm(farmer, "Old Farm", days_ago=9, code="FARMDE1")
        report = self.preview()
        self.assertIn("older code format", report)
        self.assertIn("1 first-farm codes are in an older format", report)

    def test_a_current_code_is_not_called_out(self):
        farmer = self.farmer("Current", days_ago=10)
        self.farm(farmer, "New Farm", days_ago=9)
        report = self.preview()
        self.assertNotIn("older code format", report)
        self.assertIn("0 first-farm codes are in an older format", report)

    def test_a_farmer_added_after_someone_with_an_older_farm_is_flagged(self):
        early = self.farmer("Entered First", days_ago=100)
        self.farm(early, "Late Farm", days_ago=5)
        later = self.farmer("Entered Second", days_ago=50)
        self.farm(later, "Early Farm", days_ago=90)
        report = self.preview()
        self.assertIn("out of step", report)
        self.assertIn("1 farmers were added before someone whose farm is older", report)
        # ...and the flag names the right farmer.
        flagged = [l for l in report.splitlines() if "<-- out of step" in l]
        self.assertEqual(len(flagged), 1)
        self.assertIn("Entered Second", flagged[0])

    def test_farmers_in_step_raise_nothing(self):
        first = self.farmer("First", days_ago=100)
        self.farm(first, "First Farm", days_ago=99)
        second = self.farmer("Second", days_ago=50)
        self.farm(second, "Second Farm", days_ago=49)
        self.assertIn("0 farmers were added before someone whose farm is older", self.preview())

    def test_the_disagreements_switch_shows_only_those(self):
        calm = self.farmer("Calm", days_ago=100)
        self.farm(calm, "Calm Farm", days_ago=99)
        odd = self.farmer("Odd", days_ago=50)
        self.farm(odd, "Odd Farm", days_ago=200)
        report = self.preview("--disagreements")
        self.assertIn("Odd", report)
        self.assertNotIn("Calm Farm", report)

    def test_it_writes_nothing(self):
        farmer = self.farmer("Untouched", days_ago=10)
        before = farmer.farmer_code
        self.preview()
        farmer.refresh_from_db()
        self.assertEqual(farmer.farmer_code, before)

    def test_an_empty_database_says_so(self):
        self.assertIn("No farmers on file", self.preview())
