"""Global search must never leak past the Web-Access matrix."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from inventory.models import Item, ItemCategory
from purchase.models import Supplier
from user.models import GroupTabPermission
from user.services.global_search import global_search


class GlobalSearchTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("gsadmin", "a@x.com", "Str0ngPass!")
        self.supplier = Supplier.objects.create(name="Ganga Breeding Farm",
                                                place="Gorakhpur")
        self.item = Item.objects.create(
            description="Pre Starter Feed", item_code="ITM-9001",
            category=ItemCategory.objects.create(name="Feed"),
            valuation_method="Weighted Average", standard_cost_per_unit=50,
            usage="Produced", source="Purchased", type="Raw Material",
            item_account="Expense")

    def titles(self, result, bucket):
        return [h["title"] for h in result[bucket]]

    # ---- what it finds ----------------------------------------------------

    def test_finds_a_page_by_its_label(self):
        result = global_search(self.admin, "chicks purchase")
        self.assertIn("Chicks Purchase", self.titles(result, "pages"))

    def test_finds_a_page_by_its_code(self):
        """People type the short name, not the spelled-out label."""
        self.assertIn("Chart of Accounts",
                      self.titles(global_search(self.admin, "coa"), "pages"))

    def test_finds_a_master_record(self):
        result = global_search(self.admin, "ganga")
        self.assertIn("Ganga Breeding Farm", self.titles(result, "records"))

    def test_a_record_hit_links_to_its_list_page_prefiltered(self):
        hit = next(h for h in global_search(self.admin, "ganga")["records"]
                   if h["title"] == "Ganga Breeding Farm")
        self.assertEqual(hit["url"], reverse("supplier") + "?find=Ganga%20Breeding%20Farm")

    def test_every_word_must_match(self):
        self.assertEqual(global_search(self.admin, "ganga rajasthan")["records"], [])

    def test_words_may_match_different_fields(self):
        """'ganga gorakhpur' is name + place, one word to each field."""
        self.assertIn("Ganga Breeding Farm",
                      self.titles(global_search(self.admin, "ganga gorakhpur"), "records"))

    def test_an_item_is_found_by_code(self):
        self.assertIn("Pre Starter Feed",
                      self.titles(global_search(self.admin, "ITM-9001"), "records"))

    def test_an_exact_label_outranks_a_longer_one(self):
        pages = global_search(self.admin, "supplier")["pages"]
        self.assertEqual(pages[0]["title"], "Supplier")

    def test_a_short_query_is_ignored(self):
        """One character would match most of the ERP - not worth a round trip."""
        self.assertEqual(global_search(self.admin, "s")["total"], 0)

    # ---- what it must not find -------------------------------------------

    def test_a_restricted_user_sees_only_their_own_modules(self):
        User = get_user_model()
        clerk = User.objects.create_user("stockclerk", "s@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Stock Clerk")
        clerk.groups.add(group)
        # Inventory items only - no Purchase access at all.
        GroupTabPermission.objects.create(group=group, tab_code="items", can_view=True)

        result = global_search(clerk, "feed")
        self.assertIn("Pre Starter Feed", self.titles(result, "records"))
        # The supplier lives behind a tab this user cannot view.
        self.assertNotIn("Ganga Breeding Farm",
                         self.titles(global_search(clerk, "ganga"), "records"))
        self.assertEqual(global_search(clerk, "ganga")["records"], [])

    def test_a_restricted_user_sees_only_their_own_pages(self):
        User = get_user_model()
        clerk = User.objects.create_user("pageclerk", "p@x.com", "Str0ngPass!")
        group = Group.objects.create(name="Page Clerk")
        clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="items", can_view=True)

        titles = self.titles(global_search(clerk, "supplier"), "pages")
        self.assertEqual(titles, [], "a page from a forbidden module was offered")

    # ---- the endpoint -----------------------------------------------------

    def test_endpoint_requires_a_login(self):
        response = self.client.get(reverse("global_search_api"), {"q": "ganga"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

    def test_endpoint_returns_the_search(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("global_search_api"), {"q": "ganga"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Ganga Breeding Farm",
                      [h["title"] for h in response.json()["records"]])

    def test_endpoint_tolerates_a_missing_query(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("global_search_api"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

    def test_the_dashboard_renders_the_search_box(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn('id="gs-input"', html)
        self.assertIn('id="gs-panel"', html)
        # The JS builds its fetch URL from {% url %}; a renamed route must
        # break here rather than leave a search box that silently does nothing.
        self.assertIn(reverse("global_search_api"), html)
        # Results open in a new tab, leaving the dashboard where it was.
        self.assertIn('target="_blank" rel="noopener"', html)

    # ---- the sources stay honest -----------------------------------------

    def test_every_record_source_is_wired_to_a_real_tab_and_field(self):
        """A renamed model field or tab code must fail here, not in production
        as an empty search box."""
        from django.urls import NoReverseMatch
        from user.access import ALL_TAB_CODES
        from user.services.global_search import RECORD_SOURCES, _load

        for source in RECORD_SOURCES:
            with self.subTest(source=source.kind):
                self.assertIn(source.tab, ALL_TAB_CODES)
                try:
                    reverse(source.tab)
                except NoReverseMatch:
                    self.fail(f"{source.kind}: tab '{source.tab}' is not routable")
                model = _load(source.model_path)
                names = {f.name for f in model._meta.get_fields()}
                for field in source.fields + source.title + source.subtitle:
                    self.assertIn(field, names, f"{source.kind}.{field}")
