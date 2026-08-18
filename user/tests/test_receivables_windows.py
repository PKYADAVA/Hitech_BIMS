"""Receivables: the total owed, and how recently the late part went late.

The card used to say "Overdue" and "Due today", which answers whether there is
a problem but not whether it is this week's problem or one that has been sitting
for a year. It now leads on the total and breaks the overdue money into three
nested windows — a month, a week, two days — so the last figure is the one a
collection call can still be early for.

Nested, not partitioned: money two days late is inside all three.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from sales.models import Customer, SalesInvoice
from user.services.dashboard_widgets import dashboard_widgets


class ReceivableWindowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = get_user_model().objects.create_superuser(
            "rwadmin", "rw@x.com", "Str0ngPass!")
        self.today = timezone.localdate()

    def customer(self, name, owed, days_standing, credit_period=0):
        """A customer owing `owed`, whose balance has stood `days_standing`.

        The balance is raised by an invoice and never receipted, which is what
        makes the gap the age of that invoice — the same reading the Customer
        Balance report takes.
        """
        # phone and mobile are unique on Contact; blank collides on the second.
        n = Customer.objects.count()
        c = Customer.objects.create(name=name, credit_period=credit_period,
                                    phone=f"9{n:09d}", mobile=f"8{n:09d}")
        SalesInvoice.objects.create(
            customer=c, date=self.today - timedelta(days=days_standing),
            net_amount=Decimal(owed), is_active=True)
        return c

    def stats(self):
        w = next(x for x in dashboard_widgets(self.admin, use_cache=False)
                 if x["key"] == "receivables")
        return {s["label"]: s for s in w["stats"]}

    def money(self, label):
        return self.stats()[label]["value"]

    def test_the_total_is_everything_owed_whether_late_or_not(self):
        self.customer("Within terms", 10000, days_standing=5, credit_period=30)
        self.customer("Long overdue", 25000, days_standing=400)
        self.assertEqual(self.money("Total receivable"), "₹35,000")

    def test_each_window_holds_what_went_late_inside_it(self):
        self.customer("Yesterday", 1000, days_standing=1)
        self.customer("Five days", 2000, days_standing=5)
        self.customer("Three weeks", 4000, days_standing=21)
        self.customer("Half a year", 8000, days_standing=180)
        self.assertEqual(self.money("Overdue ≤ 2 days"), "₹1,000")
        self.assertEqual(self.money("Overdue ≤ 1 week"), "₹3,000")
        self.assertEqual(self.money("Overdue ≤ 1 month"), "₹7,000")
        # The half-year balance is in none of them, but it is in the total.
        self.assertEqual(self.money("Total receivable"), "₹15,000")

    def test_the_windows_nest_rather_than_partition(self):
        """One balance, two days late, counts in all three."""
        self.customer("Just late", 5000, days_standing=2)
        for label in ("Overdue ≤ 2 days", "Overdue ≤ 1 week", "Overdue ≤ 1 month"):
            self.assertEqual(self.money(label), "₹5,000", label)

    def test_the_credit_period_is_what_lateness_is_measured_from(self):
        """Thirty days standing on thirty days' credit is not late at all."""
        self.customer("On terms", 9000, days_standing=30, credit_period=30)
        self.assertEqual(self.money("Total receivable"), "₹9,000")
        for label in ("Overdue ≤ 2 days", "Overdue ≤ 1 week", "Overdue ≤ 1 month"):
            self.assertEqual(self.money(label), "₹0", label)

    def test_a_day_past_the_credit_period_is_a_day_late_not_a_month(self):
        """The window measures from the due date, not from the invoice."""
        self.customer("Just over", 6000, days_standing=31, credit_period=30)
        self.assertEqual(self.money("Overdue ≤ 2 days"), "₹6,000")

    def test_a_customer_counts_once_and_the_card_says_how_many(self):
        self.customer("A", 1000, days_standing=3)
        self.customer("B", 1000, days_standing=4)
        self.assertEqual(self.stats()["Overdue ≤ 1 week"]["sub"], "2 customers")
        self.assertEqual(self.stats()["Overdue ≤ 2 days"]["sub"], "0 customers")

    def test_an_empty_window_is_not_dressed_up_as_a_problem(self):
        self.customer("Ancient", 1000, days_standing=365)
        self.assertIsNone(self.stats()["Overdue ≤ 2 days"]["tone"])
        self.assertEqual(self.stats()["Overdue ≤ 1 month"]["tone"], None)

    def test_a_late_window_is_flagged(self):
        self.customer("Late", 1000, days_standing=3)
        self.assertEqual(self.stats()["Overdue ≤ 1 week"]["tone"], "bad")

    def test_a_customer_in_credit_is_not_receivable_at_all(self):
        """An advance is money we hold, not money we are owed."""
        c = Customer.objects.create(name="Paid ahead", credit_period=0,
                                    phone="9999999999", mobile="8999999999")
        SalesInvoice.objects.create(customer=c, date=self.today - timedelta(days=10),
                                    net_amount=Decimal("-4000"), is_active=True)
        self.assertEqual(self.money("Total receivable"), "₹0")
        self.assertEqual(self.money("Overdue ≤ 1 month"), "₹0")
