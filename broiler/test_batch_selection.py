"""Which batch a Daily Entry / Medicine Entry is filed against.

Before this, the forms resolved the batch themselves: `_active_batch_for_farm`
took whichever open batch sorted first, the Batch box was a read-only display
of the name, and the save path resolved it a second time. A farm running two
flocks at once therefore filed entries against one of them with nothing on
screen saying which, and no way to choose the other.

Now the lookups report every open batch, the forms fill the box in when there
is exactly one and ask when there is more, and the save path uses what was
chosen — checked against the farm, because the id comes from the browser.
"""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)
from broiler.views import (_batch_options, _resolve_batch,
                           daily_entry_lookup_payload,
                           medicine_entry_farm_lookup)


class BatchSelectionTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.other_farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="L1", farm_name="Other Farm", farm_capacity=5000)

        User = get_user_model()
        self.user = User.objects.create_superuser("bs_user", "bs@x.com",
                                                  "Str0ngPass!")
        self.client.force_login(self.user)

    def batch(self, farm, name, days_ago=10, closed=False):
        return BroilerBatch.objects.create(
            broiler_farm=farm, batch_name=name,
            start_date=self.today - timedelta(days=days_ago),
            is_closed=closed,
            end_date=self.today - timedelta(days=1) if closed else None)

    # ---- what the lookup reports -------------------------------------------

    def test_one_open_batch_is_reported_and_resolved(self):
        batch = self.batch(self.farm, "B1")
        payload = daily_entry_lookup_payload(str(self.farm.id))
        self.assertEqual([b["id"] for b in payload["batches"]], [batch.id])
        self.assertEqual(payload["batch"], batch.id)

    def test_both_open_batches_are_reported(self):
        """The form fills the box in for one and asks when there are two, so
        it has to be told about both."""
        first = self.batch(self.farm, "B1", days_ago=30)
        second = self.batch(self.farm, "B2", days_ago=5)
        payload = daily_entry_lookup_payload(str(self.farm.id))
        self.assertEqual({b["id"] for b in payload["batches"]},
                         {first.id, second.id})

    def test_a_closed_batch_is_not_offered(self):
        self.batch(self.farm, "Done", days_ago=90, closed=True)
        live = self.batch(self.farm, "Live", days_ago=5)
        payload = daily_entry_lookup_payload(str(self.farm.id))
        self.assertEqual([b["id"] for b in payload["batches"]], [live.id])

    def test_a_farm_with_no_open_batch_reports_none(self):
        self.batch(self.farm, "Done", days_ago=90, closed=True)
        self.assertEqual(daily_entry_lookup_payload(str(self.farm.id))["batches"], [])

    def test_the_medicine_lookup_reports_the_same_batches(self):
        """It carries its own copy of this lookup and has to agree."""
        first = self.batch(self.farm, "B1", days_ago=30)
        second = self.batch(self.farm, "B2", days_ago=5)
        request = RequestFactory().get("/x", {"farm": self.farm.id})
        request.user = self.user
        payload = json.loads(medicine_entry_farm_lookup(request).content)
        self.assertEqual({b["id"] for b in payload["batches"]},
                         {first.id, second.id})

    # ---- choosing one -------------------------------------------------------

    def test_a_chosen_batch_wins_over_the_default(self):
        older = self.batch(self.farm, "Older", days_ago=30)
        self.batch(self.farm, "Newer", days_ago=5)          # the default pick
        payload = daily_entry_lookup_payload(str(self.farm.id),
                                             batch_id=str(older.id))
        self.assertEqual(payload["batch"], older.id)

    def test_the_age_follows_the_chosen_batch(self):
        """Age is counted from that batch's placement, so choosing the other
        flock has to change it — otherwise the choice is cosmetic."""
        older = self.batch(self.farm, "Older", days_ago=30)
        newer = self.batch(self.farm, "Newer", days_ago=5)
        old_age = daily_entry_lookup_payload(str(self.farm.id),
                                             self.today.isoformat(),
                                             str(older.id))["age_days"]
        new_age = daily_entry_lookup_payload(str(self.farm.id),
                                             self.today.isoformat(),
                                             str(newer.id))["age_days"]
        self.assertEqual(old_age, 30)
        self.assertEqual(new_age, 5)

    def test_a_batch_from_another_farm_is_refused(self):
        """The id arrives from the browser. Trusting it would post entries
        straight into a flock on a farm the form never named."""
        mine = self.batch(self.farm, "Mine")
        theirs = self.batch(self.other_farm, "Theirs")
        self.assertEqual(_resolve_batch(self.farm.id, theirs.id), mine)

    def test_a_junk_batch_id_falls_back_rather_than_crashing(self):
        mine = self.batch(self.farm, "Mine")
        self.assertEqual(_resolve_batch(self.farm.id, 999999), mine)

    def test_no_farm_resolves_to_nothing(self):
        self.assertIsNone(_resolve_batch(None, None))
        self.assertEqual(_batch_options(None), [])

    # ---- what actually gets saved -------------------------------------------

    def test_the_entry_is_saved_against_the_chosen_batch(self):
        older = self.batch(self.farm, "Older", days_ago=30)
        self.batch(self.farm, "Newer", days_ago=5)          # would win by default
        response = self.client.post(
            reverse("daily_entry_api_list"),
            data=json.dumps({"supervisor": self.supervisor.id,
                             "date": self.today.isoformat(),
                             "rows": [{"farm": self.farm.id, "batch": older.id,
                                       "date": self.today.isoformat(),
                                       "mortality": 2}]}),
            content_type="application/json")
        self.assertIn(response.status_code, (200, 201))
        self.assertEqual(DailyEntry.objects.get().batch, older)

    def test_a_row_with_no_batch_still_saves_against_the_open_one(self):
        """The mobile client and older saved sheets send no batch; they must
        keep working."""
        batch = self.batch(self.farm, "Only")
        response = self.client.post(
            reverse("daily_entry_api_list"),
            data=json.dumps({"supervisor": self.supervisor.id,
                             "date": self.today.isoformat(),
                             "rows": [{"farm": self.farm.id,
                                       "date": self.today.isoformat(),
                                       "mortality": 1}]}),
            content_type="application/json")
        self.assertIn(response.status_code, (200, 201))
        self.assertEqual(DailyEntry.objects.get().batch, batch)

    def test_a_batch_from_another_farm_is_refused_on_save_too(self):
        mine = self.batch(self.farm, "Mine")
        theirs = self.batch(self.other_farm, "Theirs")
        self.client.post(
            reverse("daily_entry_api_list"),
            data=json.dumps({"supervisor": self.supervisor.id,
                             "date": self.today.isoformat(),
                             "rows": [{"farm": self.farm.id, "batch": theirs.id,
                                       "date": self.today.isoformat(),
                                       "mortality": 1}]}),
            content_type="application/json")
        self.assertEqual(DailyEntry.objects.get().batch, mine)


class FormRenderTests(TestCase):
    """The three forms still render.

    The batch selector and the supervisor cascade are written as JavaScript
    inside Django templates, where a stray brace or an unclosed tag is a
    server-side error rather than a broken script — worth a smoke check that
    each page comes back at all.
    """

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("fr_user", "fr@x.com",
                                                  "Str0ngPass!")
        self.client.force_login(self.user)

    def assertRenders(self, url_name):
        response = self.client.get(reverse(url_name))
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_the_daily_entry_form_renders_a_batch_select(self):
        html = self.assertRenders("daily_entry_add")
        self.assertIn("form-select batch", html)
        self.assertIn("fillBatchSelect", html)

    def test_the_single_entry_form_renders_a_batch_select(self):
        html = self.assertRenders("daily_entry_single_add")
        self.assertIn('id="batch"', html)
        self.assertIn("fillBatchSelect", html)

    def test_the_medicine_form_renders_a_batch_select_and_a_cascade(self):
        html = self.assertRenders("medicine_entry_add")
        self.assertIn("form-select batch", html)
        self.assertIn("fillBatchSelect", html)
        # The cascade this form was missing entirely.
        self.assertIn("FARMS_BY_SUPERVISOR", html)

    def test_no_form_still_ships_a_readonly_batch_box(self):
        """The old read-only input is what made the choice invisible."""
        for url_name in ("daily_entry_add", "daily_entry_single_add",
                         "medicine_entry_add"):
            with self.subTest(page=url_name):
                self.assertNotIn('class="form-control bg-light batch" readonly',
                                 self.assertRenders(url_name))
