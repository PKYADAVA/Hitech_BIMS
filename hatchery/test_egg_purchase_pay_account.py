"""An egg purchase can be booked before anyone has decided how it is paid.

Pay Account was mandatory — a red asterisk on the form, ``required`` on the
select and a non-null column behind it — so a load of eggs arriving at the
hatchery could not be recorded until someone settled which account would
settle it. Nothing downstream reads the field: it is stored and shown back,
never posted, so the purchase never needed it to exist.
"""
import json
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from account.models import ChartOfAccount
from hatchery.models import EggPurchase
from inventory.models import Item, ItemCategory, Warehouse
from purchase.models import Supplier


class EggPurchasePayAccountTests(TestCase):
    def setUp(self):
        self.supplier = Supplier.objects.create(name="Verma Eggs")
        self.warehouse = Warehouse.objects.create(name="Hatchery Store")
        category = ItemCategory.objects.create(name="Hatching Eggs")
        self.item = Item.objects.create(item_code="EGG-001", description="Hatching Egg",
                                        category=category, standard_cost_per_unit=0)
        self.account = ChartOfAccount.objects.create(
            code="1001", description="Cash in Hand", type="Asset", status="Active")

        User = get_user_model()
        self.user = User.objects.create_superuser("hatch", "h@x.com", "Str0ngPass!")
        self.client.force_login(self.user)

    def payload(self, **over):
        body = {
            "date": date(2026, 7, 23).isoformat(),
            "supplier": self.supplier.id,
            "warehouse": self.warehouse.id,
            "payment_mode": "pay_later",
            "items": [{"item": self.item.id, "rcv_qty": "1000", "rate": "6.50"}],
        }
        body.update(over)
        return body

    def post(self, body):
        """201 on create — asserted here so each test reads as one claim."""
        res = self.client.post(reverse("egg_purchase_api_list"),
                               data=json.dumps(body),
                               content_type="application/json")
        self.assertEqual(res.status_code, 201, res.content)
        return res

    def test_a_purchase_saves_with_no_pay_account(self):
        res = self.post(self.payload())
        ep = EggPurchase.objects.get(id=res.json()["id"])
        self.assertIsNone(ep.pay_account_id)

    def test_a_blank_pay_account_is_read_as_none_not_looked_up(self):
        """The form posts "" for an untouched select, which used to 404."""
        res = self.post(self.payload(pay_account=""))
        self.assertIsNone(EggPurchase.objects.get(id=res.json()["id"]).pay_account_id)

    def test_a_pay_account_is_still_kept_when_one_is_chosen(self):
        res = self.post(self.payload(pay_account=self.account.id))
        ep = EggPurchase.objects.get(id=res.json()["id"])
        self.assertEqual(ep.pay_account_id, self.account.id)

    def test_an_account_can_be_cleared_on_edit(self):
        first = self.post(self.payload(pay_account=self.account.id)).json()["id"]
        res = self.client.put(
            reverse("egg_purchase_api_detail", args=[first]),
            data=json.dumps(self.payload(pay_account="")),
            content_type="application/json")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIsNone(EggPurchase.objects.get(id=first).pay_account_id)

    def test_the_model_itself_accepts_a_missing_account(self):
        """``full_clean`` runs on the save path, so blank has to be legal on
        the field and not merely absent from the payload."""
        ep = EggPurchase(date=date(2026, 7, 23), supplier=self.supplier,
                         warehouse=self.warehouse, payment_mode="pay_later")
        ep.full_clean(exclude=["transaction_no"])       # must not raise

    def test_the_form_no_longer_marks_it_required(self):
        html = self.client.get(reverse("egg_purchase_add")).content.decode()
        field = html[html.index('for="pay_account"'):html.index('for="freight_account"')]
        self.assertNotIn("required", field)
        self.assertNotIn("text-danger", field)
