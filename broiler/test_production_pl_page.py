"""The Production P&L page has to render before a batch is chosen.

Opening the report with no batch — which is how anyone arrives at it — raised
NoReverseMatch and took the whole page down with a 500. The entry-save handler
in the page's script reverses a URL from ``batch.pk``, and with no batch that
resolves to an empty string, which matches no pattern.

The handler is only meaningful once a batch is on screen; the filter bar under
it is what the empty state exists for, and has to keep working.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer, Region,
                            Supervisor)


class ProductionPlPageTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        sup = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=sup, farmer=farmer, region=region,
            line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B-1",
            start_date=self.today - timedelta(days=30))

        User = get_user_model()
        self.user = User.objects.create_superuser("pl", "pl@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def page(self, **params):
        return self.client.get(reverse("production_pl_report"), params)

    def test_it_opens_with_no_batch_chosen(self):
        """How everyone arrives at the report."""
        self.assertEqual(self.page().status_code, 200)

    def test_the_empty_page_does_not_carry_a_save_url(self):
        """There is nothing to save to, and reversing one was the crash."""
        self.assertNotIn("/entry", self.page().content.decode())

    def test_the_filter_bar_still_runs_on_the_empty_page(self):
        """Choosing a batch is the entire point of that state, so the script
        under the guarded handler must not be skipped with it."""
        self.assertIn("filterBatches", self.page().content.decode())

    def test_choosing_a_batch_wires_the_save_url_back_up(self):
        html = self.page(batch=self.batch.id).content.decode()
        self.assertIn(f"/{self.batch.id}/entry", html)

    def test_a_blank_batch_parameter_is_read_as_no_batch(self):
        """A select reset to "All" posts an empty string, not a missing key."""
        self.assertEqual(self.page(batch="").status_code, 200)

    def test_a_batch_that_does_not_exist_does_not_crash(self):
        self.assertEqual(self.page(batch=99999).status_code, 200)
