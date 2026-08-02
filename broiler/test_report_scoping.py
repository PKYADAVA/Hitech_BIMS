"""Every broiler report reads only the rows the signed-in user is scoped to.

The Chicks Placement Report was the reported case, but it was not special: an
audit of views that narrow their option lists found the same shape across the
module — scoped dropdowns over an unscoped queryset. Leaving the filters on
"All", the default, returned the whole company; naming another branch in the
query string worked whether or not the dropdown offered it.

Naming note: the two sides are "Mineglade" and "Farville" rather than
MineFarm/TheirFarm, because these reports show a supervisor column and
``"MineFarm"[:8]`` is still ``"MineFarm"`` — an assertion meant for the farm
column was matching the supervisor's name instead, and passing for the wrong
reason. Each side's farm, batch and supervisor all carry its own token.
"""
import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from user.models import GroupAccessProfile, GroupTabPermission

MINE, THEIRS = "mineglade", "farville"


class BroilerReportScopingTests(TestCase):
    """One farm in the user's branch, one outside it, each with a batch and a
    day's entry. Every report below should show the first and not the second."""

    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        self.akbarpur = Branch.objects.create(branch_name="Akbarpur",
                                              region=region, prefix="AKB")
        self.bahraich = Branch.objects.create(branch_name="Bahraich",
                                              region=region, prefix="BHR")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")

        self.mine, self.mine_batch = self.farm_with_batch(
            "Mineglade", self.akbarpur, farmer, region)
        self.theirs, self.theirs_batch = self.farm_with_batch(
            "Farville", self.bahraich, farmer, region)

        User = get_user_model()
        self.user = User.objects.create_user("brs_user", "b@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="Akbarpur Team")
        self.user.groups.add(self.group)
        for tab in ("day_record_report", "farm_detailed_daily_entry_report",
                    "live_flock_summary_report", "lifting_report",
                    "batch_wise_feed_scheduling_report", "broiler_batch_report",
                    "farm_location_capture_list"):
            GroupTabPermission.objects.create(group=self.group, tab_code=tab,
                                              can_view=True)
        self.client.force_login(self.user)

    def farm_with_batch(self, name, branch, farmer, region):
        farm = BroilerFarm.objects.create(
            branch=branch, farmer=farmer, region=region, line="L1",
            supervisor=Supervisor.objects.create(branch=branch,
                                                 name="%s Sup" % name),
            farm_name=name, farm_capacity=5000)
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, batch_name="%s-B1" % name,
            start_date=self.today - timedelta(days=10))
        DailyEntry.objects.create(farm=farm, batch=batch, date=self.today,
                                  supervisor=farm.supervisor, mortality=1)
        return farm, batch

    def limit_to_akbarpur(self):
        profile = GroupAccessProfile.objects.create(
            group=self.group, access_type="sub_admin",
            all_branches=False, all_farms=False)
        profile.branches.add(self.akbarpur)
        profile.farms.add(self.mine)
        return profile

    # ---- helpers -----------------------------------------------------------

    def page(self, url_name, **params):
        return self.client.get(reverse(url_name), params).content.decode().lower()

    def rows(self, url_name, **params):
        """The table bodies only.

        The farm and supervisor dropdowns legitimately name every farm the
        *user* may pick, so searching the whole page for a farm name answers a
        question about the filter bar rather than about the result set.
        ``<tbody>`` carries attributes on several of these reports, so the
        opening tag has to be matched loosely.
        """
        html = self.page(url_name, **params)
        return "\n".join(re.findall(r"<tbody[^>]*>(.*?)</tbody>", html, re.S))

    def assertOnlyMine(self, url_name, **params):
        with self.subTest(page=url_name):
            self.assertIn(MINE, self.rows(url_name, **params))
            # Absence is asserted over the whole page: for a scoped user the
            # dropdowns are narrowed too, so the other farm should appear
            # nowhere at all.
            self.assertNotIn(THEIRS, self.page(url_name, **params))

    # ---- the default view, every filter on "All" ---------------------------

    def test_the_daily_entry_reports_show_only_the_users_farms(self):
        self.limit_to_akbarpur()
        self.assertOnlyMine("day_record_report", date=self.today.isoformat())
        self.assertOnlyMine("farm_detailed_daily_entry_report",
                            from_date=(self.today - timedelta(days=1)).isoformat(),
                            to_date=self.today.isoformat())

    def test_the_flock_reports_show_only_the_users_farms(self):
        self.limit_to_akbarpur()
        self.assertOnlyMine("live_flock_summary_report")
        # This one renders nothing until the filter form is submitted.
        self.assertOnlyMine("batch_wise_feed_scheduling_report", submit="1")

    def test_the_batch_picker_offers_only_the_users_batches(self):
        self.limit_to_akbarpur()
        html = self.page("broiler_batch_report")
        self.assertIn("mineglade-b1", html)
        self.assertNotIn("farville-b1", html)

    # ---- the query string is not a dropdown --------------------------------

    def test_naming_another_branch_does_not_widen_the_day_record(self):
        self.limit_to_akbarpur()
        self.assertNotIn(THEIRS, self.rows("day_record_report",
                                           date=self.today.isoformat(),
                                           branch=str(self.bahraich.id)))

    def test_naming_another_farm_does_not_widen_the_detailed_report(self):
        self.limit_to_akbarpur()
        self.assertNotIn(THEIRS, self.rows(
            "farm_detailed_daily_entry_report",
            from_date=(self.today - timedelta(days=1)).isoformat(),
            to_date=self.today.isoformat(),
            farm=str(self.theirs.id)))

    def test_a_batch_outside_the_scope_is_not_opened_by_id(self):
        """The picker will not list it, but the report is reachable by URL."""
        self.limit_to_akbarpur()
        self.assertNotIn(THEIRS, self.page("broiler_batch_report",
                                           batch=str(self.theirs_batch.id)))

    def test_the_location_capture_register_is_scoped(self):
        """Its JSON feed scoped nothing at all, so a sweep for pages that scope
        their option lists could not have found it."""
        from broiler.models import FarmLocationCapture

        for farm in (self.mine, self.theirs):
            FarmLocationCapture.objects.create(farm=farm, date=self.today,
                                               latitude=26.7, longitude=83.3)
        self.limit_to_akbarpur()

        payload = self.client.get(reverse("farm_location_capture_api")).json()
        farms = {(row.get("farm") or "").lower() for row in payload}
        self.assertIn(MINE, farms)
        self.assertNotIn(THEIRS, farms)

    # ---- fail-open ---------------------------------------------------------

    def test_an_unscoped_user_still_reads_every_farm(self):
        """A group with no access profile is unrestricted, so this cannot break
        an account that worked yesterday."""
        rows = self.rows("day_record_report", date=self.today.isoformat())
        self.assertIn(MINE, rows)
        self.assertIn(THEIRS, rows)
