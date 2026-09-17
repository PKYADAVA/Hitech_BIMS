"""Item Price List changes through Change Requests.

A user without the Edit or Delete right on the price list proposes a price
change or a deletion; someone who holds the right approves it, the same as on
every other register. Nothing moves until the approval, and the change log
records who approved it and that it came through a request.
"""
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import get_resolver, reverse
from django.utils import timezone

from hatchery.change_requests import CHANGE_REQUEST_HANDLERS
from hatchery.models import ChangeRequest
from inventory.models import Item, ItemCategory, ItemPriceList, ItemPriceListAudit
from user.models import GroupAccessProfile, GroupTabPermission


class PriceChangeRequestTests(TestCase):

    def setUp(self):
        # Handlers register from each app's views.py, imported via the URLconf.
        get_resolver().url_patterns
        self.today = timezone.localdate()
        feed = ItemCategory.objects.create(name="Broiler Feed")
        self.item = Item.objects.create(
            description="Starter Feed", category=feed, valuation_method="Weighted Average",
            usage="Produced", source="Purchased", type="Raw Material", item_account="Expense",
            standard_cost_per_unit=0)
        self.entry = ItemPriceList.objects.create(
            item=self.item, price=Decimal("42"), effective_date=self.today - timedelta(days=5))

        User = get_user_model()
        self.clerk = User.objects.create_user("clerk", "c@x.com", "Str0ngPass!")
        clerks = Group.objects.create(name="Price Clerks")
        self.clerk.groups.add(clerks)
        GroupAccessProfile.objects.create(group=clerks)
        GroupTabPermission.objects.create(group=clerks, tab_code="item_price_list",
                                          can_view=True, can_add=True)
        # Raising a request is governed by the Change Requests tab, as on every
        # register: without View there, the request endpoint is refused.
        GroupTabPermission.objects.create(group=clerks, tab_code="change_requests", can_view=True)
        self.manager = User.objects.create_superuser("manager", "m@x.com", "Str0ngPass!")

    def propose(self, action, payload=None):
        self.client.force_login(self.clerk)
        body = {"module": "item_price_list", "object_id": self.entry.id,
                "action": action, "note": "Supplier rate changed"}
        if payload:
            body["payload"] = payload
        response = self.client.post("/change_request_api/", json.dumps(body),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 201, response.content)
        return ChangeRequest.objects.get(id=response.json()["id"])

    def review(self, request, decision="approve"):
        self.client.force_login(self.manager)
        return self.client.post(f"/change_request_api/{request.id}/{decision}/",
                                json.dumps({}), content_type="application/json")

    def new_price(self, price="45", on=None):
        return {"item": self.item.id, "price": price,
                "effective_date": (on or self.entry.effective_date).isoformat()}

    def test_the_price_list_is_registered(self):
        handler = CHANGE_REQUEST_HANDLERS["item_price_list"]
        self.assertEqual((handler["tab"], handler["model"]), ("item_price_list", ItemPriceList))

    def test_a_clerk_without_edit_can_only_propose(self):
        from user.access import user_can

        self.assertFalse(user_can(self.clerk, "item_price_list", "edit"))
        request = self.propose("edit", self.new_price())
        self.assertEqual(request.status, "pending")
        self.assertEqual(request.object_label,
                         f"{self.item.item_code} from {self.entry.effective_date:%d-%m-%Y}")
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.price, Decimal("42.00"))

    def test_approving_applies_the_change_and_logs_who_approved_it(self):
        request = self.propose("edit", self.new_price("45"))
        ItemPriceListAudit.objects.all().delete()
        self.assertEqual(self.review(request).status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.price, Decimal("45.00"))
        log = ItemPriceListAudit.objects.get()
        self.assertEqual((log.action, log.source, log.user), ("update", "Change Request", self.manager))
        self.assertEqual((log.old_price, log.new_price), (Decimal("42.00"), Decimal("45.00")))

    def test_rejecting_leaves_the_price_alone(self):
        request = self.propose("edit", self.new_price("45"))
        self.assertEqual(self.review(request, "reject").status_code, 200)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.price, Decimal("42.00"))

    def test_an_approved_deletion_removes_the_price_and_logs_it(self):
        request = self.propose("delete")
        ItemPriceListAudit.objects.all().delete()
        self.assertEqual(self.review(request).status_code, 200)
        self.assertFalse(ItemPriceList.objects.filter(id=self.entry.id).exists())
        log = ItemPriceListAudit.objects.get()
        self.assertEqual((log.action, log.source), ("delete", "Change Request"))

    def test_a_proposal_onto_a_date_already_priced_is_refused_on_approval(self):
        ItemPriceList.objects.create(item=self.item, price=Decimal("50"), effective_date=self.today)
        request = self.propose("edit", self.new_price("45", on=self.today))
        response = self.review(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn("already has a price", response.json()["error"])
        self.entry.refresh_from_db()
        self.assertEqual((self.entry.price, self.entry.effective_date),
                         (Decimal("42.00"), self.today - timedelta(days=5)))

    def test_the_review_page_can_read_the_current_price(self):
        self.client.force_login(self.manager)
        current = self.client.get(f"/item-price-list/{self.entry.id}/").json()
        self.assertEqual((current["price"], current["item"]), ("42.00", self.item.id))

    def test_the_page_offers_the_clerk_request_buttons(self):
        self.client.force_login(self.clerk)
        response = self.client.get(reverse("item_price_list"))
        self.assertContains(response, 'data-can-edit="0"')
        self.assertContains(response, "Request modification")
        self.assertContains(response, "js/change_requests.js")
