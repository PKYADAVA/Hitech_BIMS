"""Broiler > Master > Farmers & Farms: what the two lists gained.

The page could say how big a farm was but not whether birds were on it, and a
farmer could only be referred to by name. These cover the additions: the farmer
code, what a farmer is still missing before they can be paid, the flock on each
farm, agreement expiry, and the row and bulk actions that act on a selection.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from account.models import AccountType, ChartOfAccount, CompanyProfile
from broiler.models import (BirdSale, Branch, BroilerBatch, BroilerFarm, BroilerFarmShed,
                            DailyEntry, Farmer, FarmerGroup, Region, Supervisor)
from broiler.services.farm_overview import farmer_gaps, utilisation
from inventory.models import Item, ItemCategory, StockTransfer, Warehouse


class FarmMasterBase(TestCase):

    def setUp(self):
        self.today = timezone.localdate()
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur", region=self.region, prefix="AKB")
        self.other_branch = Branch.objects.create(branch_name="Basti", region=self.region, prefix="BST")
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="A. Pal")
        self.other_supervisor = Supervisor.objects.create(branch=self.other_branch, name="R. Singh")
        account_type = AccountType.objects.create(name="Payables", code_range_start=200000,
                                                  code_range_end=299999, report="BS")
        account = ChartOfAccount.objects.create(company=CompanyProfile.get_solo(), code="200001",
                                                description="Farmer Payable", account_type=account_type)
        self.group = FarmerGroup.objects.create(description="Baskhari Group",
                                                pay_account=account, advance_account=account)
        # One farmer who could be paid tomorrow, one who could not.
        self.ready = Farmer.objects.create(
            farmer_name="Vishvanath", mobile_no="9876500000", farmer_group=self.group,
            acc_no="123456789", ifsc_code="SBIN0001", account_holder_name="Vishvanath", pan_no="ABCDE1234F")
        self.bare = Farmer.objects.create(farmer_name="Ramesh")
        common = dict(branch=self.branch, supervisor=self.supervisor, farmer=self.ready,
                      region="East", line="Baskhari", farm_capacity=5000)
        self.busy = BroilerFarm.objects.create(farm_name="Vishvanath Farm", district="Ambedkar Nagar",
                                               **common)
        self.free = BroilerFarm.objects.create(farm_name="River Farm", **common)
        self.client.force_login(get_user_model().objects.create_superuser(
            "farmadmin", "f@x.com", "Str0ngPass!"))

    def place(self, farm, birds, days_ago=20, mortality=0, sold=0):
        """A flock on a farm: the batch, its chicks, and what has left it."""
        batch = BroilerBatch.objects.create(
            broiler_farm=farm, start_date=self.today - timedelta(days=days_ago))
        category = ItemCategory.objects.filter(name__icontains="chick").first() \
            or ItemCategory.objects.create(name="Chicks")
        item = Item.objects.create(description="Day Old Chick", category=category,
                                   valuation_method="FIFO", usage="Produced",
                                   standard_cost_per_unit=Decimal("32"))
        warehouse = Warehouse.objects.create(name=f"Central {farm.id}-{batch.id}")
        StockTransfer.objects.create(
            item=item, quantity=Decimal(birds), date=self.today - timedelta(days=days_ago),
            from_location_type="warehouse", from_warehouse=warehouse,
            to_location_type="farm", to_farm=farm, to_batch=batch)
        if mortality:
            DailyEntry.objects.create(farm=farm, batch=batch, supervisor=self.supervisor,
                                      date=self.today - timedelta(days=1), mortality=mortality)
        if sold:
            BirdSale.objects.create(farm=farm, batch=batch, birds=sold, sale_type="farmer",
                                    farmer=self.ready, date=self.today)
        return batch

    def farmers(self):
        return {r["farmer_name"]: r for r in self.client.get(reverse("farmer_list")).json()}

    def farms(self):
        return {r["farm_name"]: r for r in self.client.get(reverse("broiler_farm_list")).json()}


class FarmerCodeTests(FarmMasterBase):

    def test_every_farmer_is_issued_a_code(self):
        self.assertEqual(self.ready.farmer_code, "FRM-0001")
        self.assertEqual(self.bare.farmer_code, "FRM-0002")

    def test_the_next_code_carries_on_from_the_highest(self):
        Farmer.objects.create(farmer_name="Suresh")
        self.assertEqual(Farmer.objects.get(farmer_name="Suresh").farmer_code, "FRM-0003")

    def test_a_code_is_never_reissued_on_edit(self):
        self.ready.farmer_name = "Vishvanath Yadav"
        self.ready.save()
        self.ready.refresh_from_db()
        self.assertEqual(self.ready.farmer_code, "FRM-0001")

    def test_the_list_and_the_detail_both_carry_it(self):
        self.assertEqual(self.farmers()["Vishvanath"]["farmer_code"], "FRM-0001")
        detail = self.client.get(f"/farmer/{self.ready.id}/").json()
        self.assertEqual(detail["farmer_code"], "FRM-0001")


class FarmerReadinessTests(FarmMasterBase):

    def test_a_farmer_with_group_and_bank_is_ready_to_pay(self):
        row = self.farmers()["Vishvanath"]
        self.assertTrue(row["payable_ready"])
        self.assertEqual(row["missing"], [])

    def test_a_bare_farmer_names_what_is_missing(self):
        row = self.farmers()["Ramesh"]
        self.assertFalse(row["payable_ready"])
        self.assertEqual(row["missing"],
                         ["Farmer group", "Account number", "IFSC code", "Account holder",
                          "Mobile", "PAN"])

    def test_a_missing_contact_does_not_block_payment(self):
        # Mobile and PAN are worth chasing, but neither stops a settlement.
        self.ready.mobile_no = ""
        self.ready.save()
        row = self.farmers()["Vishvanath"]
        self.assertTrue(row["payable_ready"])
        self.assertEqual(row["missing"], ["Mobile"])

    def test_the_bank_numbers_themselves_never_reach_the_list(self):
        row = self.farmers()["Vishvanath"]
        for field in ("acc_no", "ifsc_code", "pan_no", "account_holder_name"):
            self.assertNotIn(field, row)

    def test_the_helper_orders_gaps_the_way_the_form_asks_for_them(self):
        self.assertEqual(farmer_gaps({})["payable"],
                         ["Farmer group", "Account number", "IFSC code", "Account holder"])


class FarmOccupancyTests(FarmMasterBase):

    def test_an_occupied_farm_reports_its_flock(self):
        batch = self.place(self.busy, 4000, days_ago=20, mortality=50, sold=100)
        row = self.farms()["Vishvanath Farm"]
        self.assertTrue(row["occupied"])
        self.assertEqual(row["batch_name"], batch.batch_name)
        self.assertEqual(row["age_days"], 20)
        self.assertEqual(row["live_birds"], 3850)
        self.assertEqual(row["utilisation"], 77.0)

    def test_a_farm_with_no_open_batch_is_vacant(self):
        row = self.farms()["River Farm"]
        self.assertFalse(row["occupied"])
        self.assertIsNone(row["batch_name"])
        self.assertEqual(row["live_birds"], 0)
        # Known capacity with no birds on it is 0% used, which is a different
        # answer from a farm whose capacity nobody recorded.
        self.assertEqual(row["utilisation"], 0.0)

    def test_a_closed_batch_leaves_the_farm_vacant_and_dated(self):
        batch = self.place(self.free, 1000, days_ago=60)
        batch.is_closed = True
        batch.closed_on = self.today - timedelta(days=5)
        batch.save()
        row = self.farms()["River Farm"]
        self.assertFalse(row["occupied"])
        self.assertEqual(row["vacant_since"], (self.today - timedelta(days=5)).isoformat())

    def test_two_open_flocks_are_counted_together(self):
        self.place(self.busy, 1000, days_ago=10)
        self.place(self.busy, 500, days_ago=5)
        row = self.farms()["Vishvanath Farm"]
        self.assertEqual(row["open_batches"], 2)
        self.assertEqual(row["live_birds"], 1500)

    def test_utilisation_says_nothing_when_capacity_is_unknown(self):
        self.assertIsNone(utilisation(500, 0))
        self.assertIsNone(utilisation(500, None))
        self.assertEqual(utilisation(500, 1000), 50.0)

    def test_sheds_that_disagree_with_the_farm_are_flagged(self):
        BroilerFarmShed.objects.create(farm=self.busy, shed_name="Shed 1", capacity=1200)
        row = self.farms()["Vishvanath Farm"]
        self.assertEqual(row["shed_count"], 1)
        self.assertEqual(row["shed_capacity"], 1200)
        self.assertIn("Sheds hold 1,200 but the farm is set to 5,000", row["flags"])

    def test_sheds_that_agree_raise_nothing(self):
        BroilerFarmShed.objects.create(farm=self.busy, shed_name="Shed 1", capacity=5000)
        self.assertEqual(self.farms()["Vishvanath Farm"]["flags"], [])


class AgreementTests(FarmMasterBase):

    def test_days_left_counts_down_and_then_goes_negative(self):
        self.busy.agreement_end_date = self.today + timedelta(days=30)
        self.busy.save()
        self.free.agreement_end_date = self.today - timedelta(days=4)
        self.free.save()
        rows = self.farms()
        self.assertEqual(rows["Vishvanath Farm"]["agreement_days_left"], 30)
        self.assertEqual(rows["River Farm"]["agreement_days_left"], -4)

    def test_a_farm_with_no_dates_says_so(self):
        self.assertIsNone(self.farms()["Vishvanath Farm"]["agreement_days_left"])


class FarmerStatusTests(FarmMasterBase):

    def test_one_farmer_can_be_switched_off_and_on_again(self):
        url = reverse("farmer_toggle_active", args=[self.ready.id])
        self.assertEqual(self.client.post(url).json()["status"], "inactive")
        self.assertEqual(self.client.post(url).json()["status"], "active")

    def test_switching_a_farmer_off_keeps_their_farms(self):
        self.client.post(reverse("farmer_toggle_active", args=[self.ready.id]))
        self.assertEqual(BroilerFarm.objects.filter(farmer=self.ready).count(), 2)

    def test_a_get_is_refused(self):
        self.assertEqual(self.client.get(reverse("farmer_toggle_active", args=[self.ready.id])).status_code, 405)

    def test_the_ticked_farmers_change_together(self):
        response = self.client.post(
            reverse("farmers_bulk_status"),
            {"ids": [self.ready.id, self.bare.id], "active": False},
            content_type="application/json")
        self.assertEqual(response.json()["changed"], 2)
        self.assertEqual(set(Farmer.objects.values_list("status", flat=True)), {"inactive"})

    def test_bulk_status_needs_a_selection(self):
        response = self.client.post(reverse("farmers_bulk_status"), {"ids": [], "active": True},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)


class FarmStatusTests(FarmMasterBase):

    def url(self, farm):
        return reverse("broiler_farm_toggle_active", args=[farm.id])

    def test_a_farm_switches_off_and_on_again(self):
        self.assertEqual(self.client.post(self.url(self.busy)).json()["farm_status"], "inactive")
        self.assertEqual(self.client.post(self.url(self.busy)).json()["farm_status"], "active")

    def test_a_closed_farm_reopens_rather_than_going_inactive(self):
        # Closed is where a farm ends up deliberately; the only useful thing a
        # toggle can do to one is bring it back.
        self.free.farm_status = "closed"
        self.free.save()
        self.assertEqual(self.client.post(self.url(self.free)).json()["farm_status"], "active")

    def test_switching_a_farm_off_keeps_its_flock_and_sheds(self):
        self.place(self.busy, 1000)
        BroilerFarmShed.objects.create(farm=self.busy, shed_name="Shed 1", capacity=1000)
        self.client.post(self.url(self.busy))
        row = self.farms()["Vishvanath Farm"]
        self.assertEqual((row["farm_status"], row["occupied"], row["shed_count"]),
                         ("inactive", True, 1))

    def test_a_get_is_refused(self):
        self.assertEqual(self.client.get(self.url(self.busy)).status_code, 405)


class DuplicateWarningTests(FarmMasterBase):

    def check(self, **params):
        return self.client.get(reverse("farmer_duplicate_check"), params).json()["matches"]

    def test_the_same_name_is_reported(self):
        matches = self.check(farmer_name="vishvanath")
        self.assertEqual(matches[0]["farmer_code"], "FRM-0001")
        self.assertIn("same name", matches[0]["why"])

    def test_the_same_mobile_is_reported_even_under_another_name(self):
        matches = self.check(farmer_name="Someone Else", mobile_no="9876500000")
        self.assertEqual(matches[0]["farmer_name"], "Vishvanath")
        self.assertIn("same mobile", matches[0]["why"])

    def test_the_same_pan_is_reported(self):
        self.assertIn("same PAN", self.check(pan_no="abcde1234f")[0]["why"])

    def test_the_farmer_being_edited_is_not_their_own_duplicate(self):
        self.assertEqual(self.check(farmer_name="Vishvanath", id=self.ready.id), [])

    def test_nothing_typed_means_nothing_reported(self):
        self.assertEqual(self.check(farmer_name="   "), [])

    def test_a_new_name_matches_nobody(self):
        self.assertEqual(self.check(farmer_name="Brand New", mobile_no="9000000000"), [])


class BulkSupervisorTests(FarmMasterBase):

    def move(self, farms, supervisor):
        return self.client.post(
            reverse("farms_bulk_supervisor"),
            {"ids": [f.id for f in farms], "supervisor_id": supervisor.id},
            content_type="application/json")

    def test_the_ticked_farms_move_together(self):
        response = self.move([self.busy, self.free], self.other_supervisor)
        # Both farms are at Akbarpur; the supervisor is not.
        self.assertEqual(response.status_code, 400)
        self.assertIn("Basti", response.json()["error"])

    def test_a_supervisor_from_the_same_branch_is_allowed(self):
        mover = Supervisor.objects.create(branch=self.branch, name="S. Yadav")
        response = self.move([self.busy, self.free], mover)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["changed"], 2)
        self.assertEqual(set(BroilerFarm.objects.values_list("supervisor_id", flat=True)), {mover.id})

    def test_the_refusal_names_the_farms_that_cannot_move(self):
        error = self.move([self.busy], self.other_supervisor).json()["error"]
        self.assertIn(self.busy.farm_code, error)

    def test_a_selection_and_a_supervisor_are_both_required(self):
        self.assertEqual(self.client.post(reverse("farms_bulk_supervisor"), {"ids": []},
                                          content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(reverse("farms_bulk_supervisor"),
                                          {"ids": [self.busy.id], "supervisor_id": ""},
                                          content_type="application/json").status_code, 400)


class NextFarmCodeTests(FarmMasterBase):

    def preview(self, **params):
        return self.client.get(reverse("broiler_farm_next_code"), params).json()["code"]

    def test_the_preview_is_the_code_the_next_farm_actually_gets(self):
        shown = self.preview(branch_id=self.branch.id)
        self.assertTrue(shown)
        made = BroilerFarm.objects.create(
            farm_name="New Farm", branch=self.branch, supervisor=self.supervisor,
            farmer=self.ready, region="East", line="Baskhari", farm_capacity=1000)
        self.assertEqual(made.farm_code, shown)

    def test_the_preview_moves_up_once_that_code_is_taken(self):
        first = self.preview(branch_id=self.branch.id)
        BroilerFarm.objects.create(
            farm_name="New Farm", branch=self.branch, supervisor=self.supervisor,
            farmer=self.ready, region="East", line="Baskhari", farm_capacity=1000)
        self.assertNotEqual(self.preview(branch_id=self.branch.id), first)

    def test_each_branch_has_its_own_run_of_codes(self):
        self.assertNotEqual(self.preview(branch_id=self.branch.id),
                            self.preview(branch_id=self.other_branch.id))

    def test_no_branch_means_no_code(self):
        self.assertEqual(self.preview(), "")
        self.assertEqual(self.preview(branch_id=""), "")
        self.assertEqual(self.preview(branch_id="abc"), "")
        self.assertEqual(self.preview(branch_id=999999), "")

    def test_the_form_has_somewhere_to_say_it(self):
        self.assertContains(self.client.get(reverse("branch_farm")), 'id="farm-code-hint"')


class NextFarmerCodeTests(FarmMasterBase):

    def preview(self):
        return self.client.get(reverse("farmer_next_code")).json()["code"]

    def test_the_preview_is_the_code_the_next_farmer_actually_gets(self):
        shown = self.preview()
        self.assertEqual(Farmer.objects.create(farmer_name="Suresh").farmer_code, shown)

    def test_the_preview_moves_up_once_that_code_is_taken(self):
        first = self.preview()
        Farmer.objects.create(farmer_name="Suresh")
        self.assertNotEqual(self.preview(), first)

    def test_the_form_has_somewhere_to_say_it(self):
        response = self.client.get(reverse("branch_farm"))
        self.assertContains(response, 'id="farmer_code"')
        self.assertContains(response, 'id="farmer-code-hint"')


class PageTests(FarmMasterBase):

    def test_the_page_offers_the_new_controls(self):
        response = self.client.get(reverse("branch_farm"))
        for text in ('id="bf-fr-sum"', 'id="bf-fm-sum"', 'id="bf-fr-ready"', 'id="bf-fm-flock"',
                     'id="bf-fm-agreement"', 'id="bf-fr-bulk"', 'id="bf-fm-bulk"',
                     'id="bfSupModal"', 'id="bf-dup-warn"', 'id="bf-fr-all"', 'id="bf-fm-all"'):
            self.assertContains(response, text)

    def test_the_farm_forms_farmer_picker_names_the_code_too(self):
        response = self.client.get(reverse("branch_farm"))
        self.assertContains(response, 'data-name="Vishvanath">FRM-0001 - Vishvanath')
        # The plain name rides along because the farm-name auto-fill reads it:
        # a farm should not end up called "FRM-0001 - Vishvanath".
        self.assertEqual([f["farmer_code"] for f in response.context["farmers"]],
                         ["FRM-0002", "FRM-0001"])

    def test_the_setup_request_queue_is_only_shown_when_something_waits(self):
        self.assertEqual(self.client.get(reverse("branch_farm")).context["pending_setup_requests"], 0)
        self.assertNotContains(self.client.get(reverse("branch_farm")), "Setup Requests")
