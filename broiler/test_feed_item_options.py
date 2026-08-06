"""What the Daily Entry's Feed columns are allowed to offer.

Both Feed pickers listed the whole Item master, on the web and on the phone.
Day Old Chicks was therefore offered as something to feed a flock — and
choosing it would have posted chicks into the feed-stock ledger, which chains
each entry's opening balance off the last one.

The rule itself ("a category named for feed") was written out thirteen times
across the module and the form used none of them. It lives in one place now,
and these check that both clients read it from there.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from broiler.views import chick_items, feed_items
from inventory.models import Item, ItemCategory


class FeedItemOptionTests(TestCase):
    def setUp(self):
        feed = ItemCategory.objects.create(name="Broiler Feed")
        chicks = ItemCategory.objects.create(name="Day Old Chicks")
        medicine = ItemCategory.objects.create(name="Medicine")

        self.starter = Item.objects.create(item_code="FD-001", description="Starter Crumble",
                                           category=feed, standard_cost_per_unit=0)
        self.finisher = Item.objects.create(item_code="FD-002", description="Finisher Pellet",
                                            category=feed, standard_cost_per_unit=0)
        self.chick = Item.objects.create(item_code="CHK-001", description="Day Old Chick",
                                         category=chicks, standard_cost_per_unit=0)
        self.drug = Item.objects.create(item_code="MED-001", description="Vitamin Mix",
                                        category=medicine, standard_cost_per_unit=0)

        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        BroilerFarm.objects.create(branch=branch, supervisor=supervisor, farmer=farmer,
                                   region=region, line="L1", farm_name="Green Valley Farm",
                                   farm_capacity=9000)

        User = get_user_model()
        self.user = User.objects.create_superuser("fi_user", "fi@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    # ---- the rule itself ----------------------------------------------------

    def test_feed_items_are_the_feed_category_and_nothing_else(self):
        self.assertEqual([i.item_code for i in feed_items()], ["FD-001", "FD-002"])

    def test_chick_items_stay_separate(self):
        self.assertEqual([i.item_code for i in chick_items()], ["CHK-001"])

    def test_a_second_feed_category_is_included(self):
        """Matched on the name, not an id: a site running a second feed
        category wants both, and there is no fixed id to hold on to."""
        pre = ItemCategory.objects.create(name="Pre-Starter Feed")
        Item.objects.create(item_code="FD-003", description="Pre-Starter",
                            category=pre, standard_cost_per_unit=0)
        self.assertIn("FD-003", [i.item_code for i in feed_items()])

    # ---- the web form -------------------------------------------------------

    def test_the_web_daily_entry_form_offers_feed_only(self):
        page = self.client.get(reverse("daily_entry_add")).content.decode()
        self.assertIn("Starter Crumble", page)
        self.assertIn("Finisher Pellet", page)
        self.assertNotIn("Day Old Chick", page)
        self.assertNotIn("Vitamin Mix", page)

    def test_the_single_batch_form_offers_feed_only(self):
        page = self.client.get(reverse("daily_entry_single_add")).content.decode()
        self.assertIn("Starter Crumble", page)
        self.assertNotIn("Day Old Chick", page)

    # ---- the phone ----------------------------------------------------------

    def test_the_phone_endpoint_answers_the_same_list(self):
        rows = self.client.get("/api/v1/broiler/feed-items").json()["data"]
        self.assertEqual([r["item_code"] for r in rows],
                         [i.item_code for i in feed_items()])
        self.assertNotIn("CHK-001", [r["item_code"] for r in rows])

    def test_the_phone_forms_point_at_that_endpoint(self):
        """Both Feed pickers, on the grid screen and in the form schema —
        one of the two being left on /items/ is the likely regression."""
        import pathlib

        from django.conf import settings

        mobile = pathlib.Path(settings.BASE_DIR) / "mobile" / "src"
        grid = (mobile / "screens" / "DailyEntryGridScreen.tsx")
        schema = (mobile / "config" / "forms.ts")
        if not grid.exists():
            self.skipTest("mobile client not present")

        text = grid.read_text(encoding="utf-8")
        self.assertEqual(text.count('optionsPath: "/broiler/feed-items"'), 2)

        text = schema.read_text(encoding="utf-8")
        self.assertIn('FEED_ITEM("feed_1"', text)
        self.assertIn('FEED_ITEM("feed_2"', text)
