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
import os
import re
import shutil
import subprocess
import tempfile
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


class MedicineEntryDateTests(TestCase):
    """Medicine consumption is recorded on the day it happened.

    The row's Date box was read-only and fixed at today, and the form did not
    even send it — the payload carried one top-level `date` for the sheet. So a
    dose given on Tuesday and typed up on Thursday was filed as Thursday's,
    with Thursday's age and Thursday's opening stock. The save path already
    honoured a per-row date; nothing was sending one.
    """

    def setUp(self):
        from inventory.models import Item, ItemCategory

        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B1",
            start_date=self.today - timedelta(days=20))
        self.medicine = Item.objects.create(
            description="Vitamin AD3E",
            category=ItemCategory.objects.create(name="Medicine"),
            valuation_method="Weighted Average", standard_cost_per_unit=100,
            usage="Consumed", source="Purchased", type="Raw Material",
            item_account="Expense")

        User = get_user_model()
        self.user = User.objects.create_superuser("med_user", "m@x.com",
                                                  "Str0ngPass!")
        self.client.force_login(self.user)

    def post(self, rows):
        return self.client.post(
            reverse("medicine_entry_api_list"),
            data=json.dumps({"supervisor": self.supervisor.id,
                             "date": self.today.isoformat(), "rows": rows}),
            content_type="application/json")

    def row(self, days_ago, qty=5):
        return {"farm": self.farm.id, "batch": self.batch.id,
                "date": (self.today - timedelta(days=days_ago)).isoformat(),
                "item": self.medicine.id, "qty": qty}

    def test_a_back_dated_dose_keeps_its_own_date(self):
        from broiler.models import MedicineVaccineEntry

        response = self.post([self.row(days_ago=4)])
        self.assertIn(response.status_code, (200, 201))
        entry = MedicineVaccineEntry.objects.get()
        self.assertEqual(entry.date, self.today - timedelta(days=4))

    def test_the_age_is_the_age_on_that_day(self):
        """Placed 20 days ago, dosed 4 days ago — age 16, not 20."""
        from broiler.models import MedicineVaccineEntry

        self.post([self.row(days_ago=4)])
        self.assertEqual(MedicineVaccineEntry.objects.get().age_days, 16)

    def test_rows_may_carry_different_dates_in_one_sheet(self):
        from broiler.models import MedicineVaccineEntry

        self.post([self.row(days_ago=6), self.row(days_ago=2)])
        dates = set(MedicineVaccineEntry.objects.values_list("date", flat=True))
        self.assertEqual(dates, {self.today - timedelta(days=6),
                                 self.today - timedelta(days=2)})

    def test_the_form_offers_an_editable_date(self):
        html = self.client.get(reverse("medicine_entry_add")).content.decode()
        self.assertIn('class="form-control date" type="date"', html)
        self.assertNotIn('class="form-control bg-light date" readonly', html)


class InlineScriptSyntaxTests(TestCase):
    """The JavaScript these forms emit actually parses.

    Most of the entry logic — the supervisor cascade, the batch selector, the
    carried farm/batch — is JavaScript written inside a Django template. A
    stray brace there is invisible to `manage.py check` and to every other test
    here: the page still returns 200, and only the browser finds out. `node
    --check` reads the rendered output the way the browser would.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node = shutil.which("node")

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("js_user", "js@x.com",
                                                  "Str0ngPass!")
        self.client.force_login(self.user)

    def assertScriptsParse(self, url_name):
        if not self.node:
            self.skipTest("node is not installed")
        html = self.client.get(reverse(url_name)).content.decode()
        # Inline blocks only: a src= tag has nothing between the tags to check.
        blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                            html, re.S)
        self.assertTrue(blocks, "no inline script found on %s" % url_name)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8") as handle:
            handle.write("\n;\n".join(blocks))
            path = handle.name
        try:
            result = subprocess.run([self.node, "--check", path],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0,
                             "%s emits invalid JavaScript:\n%s"
                             % (url_name, result.stderr[:2000]))
        finally:
            os.unlink(path)

    def test_the_daily_entry_form_script_parses(self):
        self.assertScriptsParse("daily_entry_add")

    def test_the_single_entry_form_script_parses(self):
        self.assertScriptsParse("daily_entry_single_add")

    def test_the_medicine_form_script_parses(self):
        self.assertScriptsParse("medicine_entry_add")


class FutureDateTests(TestCase):
    """A flock cannot be recorded ahead of itself.

    Single Entry's date box was editable with no cap at all, so a future date
    could be picked and saved. Everything read as-of a date — age, opening
    stock, the live-bird count — is wrong for such a row, so it is refused
    rather than clamped: clamping would save a row nobody asked for and hide
    the mistake.

    The browser guard is a courtesy. This is the check that holds, because the
    mobile client and a hand-made request both come through the same path.
    """

    def setUp(self):
        from inventory.models import Item, ItemCategory

        self.today = timezone.localdate()
        self.tomorrow = self.today + timedelta(days=1)
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B1",
            start_date=self.today - timedelta(days=10))
        self.medicine = Item.objects.create(
            description="Vitamin AD3E",
            category=ItemCategory.objects.create(name="Medicine"),
            valuation_method="Weighted Average", standard_cost_per_unit=100,
            usage="Consumed", source="Purchased", type="Raw Material",
            item_account="Expense")

        User = get_user_model()
        self.user = User.objects.create_superuser("fd_user", "fd@x.com",
                                                  "Str0ngPass!")
        self.client.force_login(self.user)

    def post_entry(self, date):
        return self.client.post(
            reverse("daily_entry_api_list"),
            data=json.dumps({"supervisor": self.supervisor.id,
                             "date": self.today.isoformat(),
                             "rows": [{"farm": self.farm.id,
                                       "batch": self.batch.id,
                                       "date": date.isoformat(),
                                       "mortality": 1}]}),
            content_type="application/json")

    def post_medicine(self, date):
        return self.client.post(
            reverse("medicine_entry_api_list"),
            data=json.dumps({"supervisor": self.supervisor.id,
                             "date": self.today.isoformat(),
                             "rows": [{"farm": self.farm.id,
                                       "batch": self.batch.id,
                                       "date": date.isoformat(),
                                       "item": self.medicine.id, "qty": 1}]}),
            content_type="application/json")

    def test_a_daily_entry_dated_tomorrow_is_refused(self):
        response = self.post_entry(self.tomorrow)
        self.assertEqual(response.status_code, 400)
        self.assertIn("later than today", response.json()["error"])
        self.assertEqual(DailyEntry.objects.count(), 0)

    def test_a_medicine_entry_dated_tomorrow_is_refused(self):
        from broiler.models import MedicineVaccineEntry

        response = self.post_medicine(self.tomorrow)
        self.assertEqual(response.status_code, 400)
        self.assertIn("later than today", response.json()["error"])
        self.assertEqual(MedicineVaccineEntry.objects.count(), 0)

    def test_today_is_still_allowed(self):
        """The boundary is the whole point: today must not be caught by it."""
        self.assertIn(self.post_entry(self.today).status_code, (200, 201))
        self.assertEqual(DailyEntry.objects.count(), 1)

    def test_a_past_date_is_still_allowed(self):
        self.assertIn(self.post_entry(self.today - timedelta(days=3)).status_code,
                      (200, 201))
        self.assertEqual(DailyEntry.objects.count(), 1)

    def test_the_refusal_is_reported_not_swallowed(self):
        """The client shows `error` from the body; a 500 would say nothing
        useful and a 201 would be a silent corruption."""
        body = self.post_entry(self.tomorrow).json()
        self.assertIn("error", body)
        self.assertTrue(body["error"])

    def test_both_editable_date_boxes_are_capped_in_the_form(self):
        for url_name in ("daily_entry_single_add", "medicine_entry_add"):
            with self.subTest(page=url_name):
                html = self.client.get(reverse(url_name)).content.decode()
                self.assertIn('max="${TODAY}"', html)
                self.assertIn("guardFutureDate", html)


class SharedFutureDateRuleTests(TestCase):
    """The rule is not Single Entry's private business.

    It lives in Hitech_BIMS.entry_dates and is applied at every transaction
    save path — broiler, inventory, sales, hatchery — and in main.js for every
    transaction date box on every page, including rows built after load.
    """

    def test_the_rule_refuses_tomorrow_and_allows_today(self):
        from Hitech_BIMS.entry_dates import reject_future_date
        from django.core.exceptions import ValidationError

        today = timezone.localdate()
        self.assertEqual(reject_future_date(today), today)
        self.assertEqual(reject_future_date(today - timedelta(days=1)),
                         today - timedelta(days=1))
        self.assertIsNone(reject_future_date(None))
        with self.assertRaises(ValidationError):
            reject_future_date(today + timedelta(days=1))

    def test_every_module_that_saves_a_transaction_date_applies_it(self):
        """A save path that parses a date and does not run it through the rule
        is one that still accepts tomorrow."""
        import pathlib
        import re

        offenders = []
        for path in ("broiler/views.py", "inventory/views.py", "sales/views.py",
                     "hatchery/views.py"):
            source = pathlib.Path(path).read_text(encoding="utf-8")
            for line in source.splitlines():
                if not re.search(r"instance\.date\s*=.*fromisoformat", line):
                    continue
                if "reject_future_date" not in line:
                    offenders.append("%s: %s" % (path, line.strip()[:80]))
        self.assertEqual(offenders, [])

    def test_the_browser_guard_ships_and_is_narrow(self):
        """Scheduling dates must not be caught by it: a hatch date, a tray
        transfer, a phase's effective_from and a financial year are all
        legitimately in the future."""
        import pathlib

        js = pathlib.Path("static/js/main.js").read_text(encoding="utf-8")
        self.assertIn("isTransactionDate", js)
        self.assertIn("data-allow-future", js)
        # Matched on the transaction-date convention only.
        self.assertIn("el.id === 'date' || el.name === 'date'", js)

    def test_the_collected_copy_is_current(self):
        """WhiteNoise serves staticfiles/, not static/ — an uncollected change
        is invisible in the browser however right the source is.

        staticfiles/ is generated and git-ignored, so this can only check a
        tree where collectstatic has actually been run; elsewhere there is
        nothing to be stale.
        """
        import pathlib

        collected = pathlib.Path("staticfiles/js/main.js")
        if not collected.exists():
            self.skipTest("staticfiles/ not built in this tree")
        self.assertIn("isTransactionDate",
                      collected.read_text(encoding="utf-8"),
                      "staticfiles/js/main.js is stale — run collectstatic")


class MobileFarmLookupParityTests(TestCase):
    """The phone and the web must answer the same question the same way.

    `/broiler/farm-lookup` — which the app's single Daily Entry form uses to
    fill in date and age — had grown its own copy of that resolution and
    drifted on three counts: it read the raw start_date column, so a batch
    placed by stock transfer reported age 0; it dated from the farm's last
    entry rather than the batch's, so a new flock inherited the previous one's;
    and with no entries it fell back to today instead of the day after
    placement. A newly placed flock therefore showed age 0 dated today, while
    the web showed the real age and the real day.
    """

    def setUp(self):
        from inventory.models import Item, ItemCategory

        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=self.supervisor, farmer=farmer,
            region=region, line="L1", farm_name="Yadav Farm", farm_capacity=5000)
        self.chick = Item.objects.create(
            description="Day Old Chicks",
            category=ItemCategory.objects.create(name="Chicks"),
            valuation_method="Weighted Average", standard_cost_per_unit=40,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

        User = get_user_model()
        self.user = User.objects.create_superuser("mfl_user", "mf@x.com",
                                                  "Str0ngPass!")
        self.client.force_login(self.user)

    def place(self, batch, days_ago):
        from inventory.models import StockTransfer

        return StockTransfer.objects.create(
            item=self.chick, to_batch=batch, quantity=1000,
            date=self.today - timedelta(days=days_ago))

    def lookup(self):
        from broiler.api import BirdSaleFarmLookupView
        from django.test import RequestFactory

        request = RequestFactory().get("/x", {"farm": self.farm.id})
        request.user = self.user
        return BirdSaleFarmLookupView.as_view()(request).data

    # ---- a batch with a start_date ------------------------------------------

    def test_a_new_batch_is_dated_the_day_after_placement_not_today(self):
        """The reported case: placed a fortnight ago, never recorded."""
        batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="New",
            start_date=self.today - timedelta(days=14))
        payload = self.lookup()
        self.assertEqual(payload["next_date"],
                         (batch.start_date + timedelta(days=1)).isoformat())
        self.assertNotEqual(payload["next_date"], self.today.isoformat())

    def test_the_age_is_the_flocks_real_age_not_zero(self):
        BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="New",
            start_date=self.today - timedelta(days=14))
        self.assertEqual(self.lookup()["age_days"], 1)   # as of next_date

    # ---- a batch placed by stock transfer, with no start_date ---------------

    def test_a_batch_with_no_start_date_still_reports_its_placement(self):
        batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                            batch_name="NoStart")
        self.place(batch, days_ago=11)
        payload = self.lookup()
        self.assertEqual(payload["start_date"],
                         (self.today - timedelta(days=11)).isoformat())
        self.assertEqual(payload["next_date"],
                         (self.today - timedelta(days=10)).isoformat())
        self.assertEqual(payload["age_days"], 1)

    # ---- a farm re-used for a second flock ----------------------------------

    def test_a_new_flock_does_not_inherit_the_previous_ones_entries(self):
        old = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="Old", is_closed=True,
            start_date=self.today - timedelta(days=90),
            end_date=self.today - timedelta(days=30))
        DailyEntry.objects.create(farm=self.farm, batch=old, supervisor=self.supervisor,
                                  date=self.today - timedelta(days=40), mortality=1)
        new = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="New",
            start_date=self.today - timedelta(days=5))
        self.assertEqual(self.lookup()["next_date"],
                         (new.start_date + timedelta(days=1)).isoformat())

    # ---- the two clients agree ----------------------------------------------

    def test_it_agrees_with_the_web_payload(self):
        """Not just 'is right' — the same, since both now resolve it once."""
        from broiler.views import daily_entry_lookup_payload

        batch = BroilerBatch.objects.create(broiler_farm=self.farm,
                                            batch_name="NoStart")
        self.place(batch, days_ago=9)
        mobile = self.lookup()
        web = daily_entry_lookup_payload(str(self.farm.id))
        for key in ("batch", "batch_name", "age_days", "start_date", "next_date"):
            with self.subTest(field=key):
                self.assertEqual(mobile[key], web[key])

    def test_it_offers_the_open_batches_too(self):
        first = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="A",
            start_date=self.today - timedelta(days=20))
        second = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="B",
            start_date=self.today - timedelta(days=3))
        names = {b["id"] for b in self.lookup()["batches"]}
        self.assertEqual(names, {first.id, second.id})
