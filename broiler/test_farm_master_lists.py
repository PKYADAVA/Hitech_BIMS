"""Broiler > Master > Farmers & Farms: the two lists.

Both lists now carry what the page filters and shows (status, farm count,
capacity, sheds, district, location) and are read straight from the database.
The farm list used to share its cache key with two other pages that stored a
different shape of data under it, so whichever page loaded first decided what
the others got.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from account.models import AccountType, ChartOfAccount, CompanyProfile
from broiler.models import Branch, BroilerFarm, Farmer, FarmerGroup, Region, Supervisor


class FarmMasterListTests(TestCase):

    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="A. Pal")
        account_type = AccountType.objects.create(name="Payables", code_range_start=200000,
                                                  code_range_end=299999, report="BS")
        account = ChartOfAccount.objects.create(company=CompanyProfile.get_solo(), code="200001",
                                                description="Farmer Payable", account_type=account_type)
        group = FarmerGroup.objects.create(description="Baskhari Group",
                                           pay_account=account, advance_account=account)
        self.farmer = Farmer.objects.create(farmer_name="Vishvanath", mobile_no="9876500000",
                                            farmer_group=group)
        self.idle = Farmer.objects.create(farmer_name="Ramesh", status="inactive")
        common = dict(branch=branch, supervisor=supervisor, farmer=self.farmer, region="East",
                      line="Baskhari", farm_capacity=5000)
        self.pinned = BroilerFarm.objects.create(
            farm_name="Vishvanath Farm", district="Ambedkar Nagar", state="Uttar Pradesh",
            farm_latitude=26.43, farm_longitude=82.54, location_verified=True, **common)
        self.unpinned = BroilerFarm.objects.create(farm_name="River Farm", farm_status="closed",
                                                   farm_type="integration", **common)
        self.client.force_login(get_user_model().objects.create_superuser("farmadmin", "f@x.com", "Str0ngPass!"))

    def farmers(self):
        return {r["farmer_name"]: r for r in self.client.get(reverse("farmer_list")).json()}

    def farms(self):
        return {r["farm_name"]: r for r in self.client.get(reverse("broiler_farm_list")).json()}

    def test_farmers_carry_status_and_farm_count(self):
        rows = self.farmers()
        self.assertEqual((rows["Vishvanath"]["status"], rows["Vishvanath"]["farm_count"]), ("active", 2))
        self.assertEqual((rows["Ramesh"]["status"], rows["Ramesh"]["farm_count"]), ("inactive", 0))
        self.assertEqual(rows["Vishvanath"]["farmer_group_name"], "Baskhari Group")

    def test_farms_carry_capacity_status_location_and_sheds(self):
        rows = self.farms()
        pinned, unpinned = rows["Vishvanath Farm"], rows["River Farm"]
        self.assertEqual((pinned["farm_capacity"], pinned["shed_count"], pinned["district"]),
                         (5000, 0, "Ambedkar Nagar"))
        self.assertEqual((pinned["location_verified"], pinned["has_location"]), (True, True))
        self.assertEqual((unpinned["has_location"], unpinned["farm_status"], unpinned["farm_type"]),
                         (False, "closed", "integration"))
        self.assertEqual((pinned["branch_name"], pinned["supervisor_name"], pinned["farmer_name"]),
                         ("Akbarpur", "A. Pal", "Vishvanath"))

    def test_another_pages_cache_cannot_change_the_lists(self):
        cache.set("broiler_farm_list", [{"id": 999, "unrelated": True}])
        cache.set("farmer_list", [{"id": 998, "unrelated": True}])
        self.assertEqual(set(self.farms()), {"Vishvanath Farm", "River Farm"})
        self.assertEqual(set(self.farmers()), {"Vishvanath", "Ramesh"})

    def test_a_new_farm_shows_at_once(self):
        self.farms()
        BroilerFarm.objects.create(farm_name="New Farm", branch=self.pinned.branch,
                                   supervisor=self.pinned.supervisor, farmer=self.idle,
                                   region="East", line="Baskhari", farm_capacity=3000)
        self.assertIn("New Farm", self.farms())
        self.assertEqual(self.farmers()["Ramesh"]["farm_count"], 1)

    def test_the_page_has_the_new_lists_and_keeps_the_farm_form(self):
        html = self.client.get(reverse("branch_farm")).content.decode()
        for text in ('id="bf-page"', 'id="farmer-table"', 'id="farm-table"', 'id="bf-fm-location"',
                     'id="bf-fr-group"', 'id="bfViewModal"', 'id="farmerFormModal"', 'id="farmFormModal"',
                     'id="visit_priority"', "Baskhari Group"):
            self.assertIn(text, html)
