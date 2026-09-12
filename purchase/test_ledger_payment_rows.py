"""A ledger with a payment in it.

Supplier Ledger answered a 500 with no dates chosen, and only sometimes when
dates were. That pattern is the whole diagnosis: no dates means every row is
included, so the bad one is always there; a range includes it only sometimes.

The bad row was a payment. `mode` stopped being a choices field when payment
modes moved to the Payment Mode master — it is a plain name now — and Django
only builds `get_<field>_display` for a field that *has* choices. So the call
that had been there for years became an AttributeError on any party with a
payment, in both ledgers at once.

Nothing caught it because this database has no payment lines at all: every
local check of the report passed, repeatedly, while production failed. So the
tests below build the row first. A report test that never exercises a payment
row is not a test of the report.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase

from account.models import ChartOfAccount
from inventory.models import Warehouse
from purchase.models import Supplier, SupplierPayment, SupplierPaymentLine
from sales.models import Customer, SalesReceipt


class LedgerWithAPaymentTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="ledger_reader", password="x", email="l@example.com")
        self.client.force_login(self.user)
        self.supplier = Supplier.objects.create(name="Ravi Feeds")
        payment = SupplierPayment.objects.create(
            date=datetime.date(2026, 7, 10),
            location=Warehouse.objects.create(name="Main Warehouse"))
        SupplierPaymentLine.objects.create(
            payment=payment, supplier=self.supplier,
            # A mode somebody added to the master — the case the old call could
            # not have rendered even if it had existed.
            mode="Paytm Business Wallet",
            pay_account=self._account(), amount=1500)

    def _account(self):
        return ChartOfAccount.objects.create(
            code="900001", description="Cash In Hand", is_postable=True)

    def ledger(self, **params):
        query = "&".join("%s=%s" % (k, v) for k, v in params.items())
        return self.client.get("/supplier-ledger/?supplier=%s&%s"
                               % (self.supplier.id, query))

    def test_the_ledger_opens_with_no_dates_chosen(self):
        """The report as it was described: submit with both boxes empty, which
        includes every row there is."""
        self.assertEqual(self.ledger(from_date="", to_date="").status_code, 200)

    def test_the_ledger_opens_with_the_payment_inside_the_range(self):
        self.assertEqual(
            self.ledger(from_date="2026-07-01", to_date="2026-07-31").status_code, 200)

    def test_the_ledger_opens_with_the_payment_outside_the_range(self):
        """This one passed all along, which is why the failure looked
        intermittent rather than total."""
        self.assertEqual(
            self.ledger(from_date="2026-01-01", to_date="2026-01-31").status_code, 200)

    def test_the_payment_mode_is_shown_as_the_master_names_it(self):
        """Not crashing is not enough — the row has to say which mode it was,
        and the value is now the label."""
        response = self.ledger(from_date="", to_date="")
        self.assertContains(response, "Paytm Business Wallet")


class CustomerLedgerTests(TestCase):
    """The same call, in the other ledger.

    sales/views.py built its receipt rows with get_mode_display() too, on
    models whose `mode` lost its choices in the same change. Customer Ledger
    was broken in exactly the same way and by the same line of reasoning, and
    nobody had reported it yet.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="cust_reader", password="x", email="cl@example.com")
        self.client.force_login(self.user)
        self.customer = Customer.objects.create(
            name="Ravi Traders", mobile="9990004444", address="Akbarpur")
        SalesReceipt.objects.create(
            customer=self.customer, date=datetime.date(2026, 7, 10),
            mode="Paytm Business Wallet", amount=900,
            receipt_account=ChartOfAccount.objects.create(
                code="900002", description="Bank", is_postable=True))

    def test_the_ledger_opens_with_no_dates_chosen(self):
        response = self.client.get("/customer-ledger/?customer=%s&from_date=&to_date="
                                   % self.customer.id)
        self.assertEqual(response.status_code, 200)

    def test_the_receipt_mode_is_shown_as_the_master_names_it(self):
        response = self.client.get("/customer-ledger/?customer=%s&from_date=&to_date="
                                   % self.customer.id)
        self.assertContains(response, "Paytm Business Wallet")


class DisplayHelperGuardTests(TestCase):
    """The class of bug, as far as a static check can reach.

    Django stops providing `get_<field>_display` the moment a field loses its
    choices, and every call becomes an AttributeError when that row is
    rendered — which here was only ever in production, where the rows are.

    This catches a name that no model gives choices to any more. It would not
    have caught the bug that prompted it: `mode` is still a choices field on
    FarmRoute, so the name looks live, and nothing static can say which model
    a given call site means. The tests above are the real guard; this one is a
    cheap net under the simpler case.
    """

    def test_no_view_asks_a_choiceless_field_for_its_display(self):
        import glob
        import io
        import re

        from django.apps import apps

        # field name -> does *any* model still give it choices?
        has_choices = {}
        for model in apps.get_models():
            for field in model._meta.concrete_fields:
                if getattr(field, "choices", None):
                    has_choices[field.name] = True

        offenders = []
        for path in glob.glob("*/views*.py") + glob.glob("*/services/*.py"):
            if "/migrations/" in path:
                continue
            source = io.open(path, encoding="utf-8").read()
            for match in re.finditer(r"get_(\w+)_display", source):
                field = match.group(1)
                # Only flag a name no model anywhere gives choices to: a name
                # that is still a choices field somewhere may well be the one
                # being called here, and this test cannot tell which.
                if not has_choices.get(field):
                    line = source[:match.start()].count("\n") + 1
                    offenders.append("%s:%d get_%s_display" % (path, line, field))
        self.assertEqual(offenders, [],
                         "these ask for a display that Django no longer builds")
