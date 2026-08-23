"""Receivables: the total owed, and how recently the late part went late.

The card used to say "Overdue" and "Due today", which answers whether there is
a problem but not whether it is this week's problem or one that has been sitting
for a year. It now leads on the total and breaks the overdue money into three
nested windows — a month, a week, two days — so the last figure is the one a
collection call can still be early for.

Nested, not partitioned: money two days late is inside all three. A balance
raised today counts from day zero, not from the day after — it is still money
owed, so it belongs in the narrowest band immediately rather than waiting a
day to appear anywhere.

Overdue is read from `gap` alone (days since the balance last moved), with no
credit-period offset netted out of it — a customer with a 30-day credit period
sitting at day 15 counts as 15 days overdue here, not 0. This card asks "how
long has this money been outstanding," a collections question; whether a party
is in breach of their agreed terms is a different question, which is what
Customer Balance's own Debit/Credit split still answers.

There is deliberately no "Total overdue"/no-ceiling band any more. There was
one, briefly, on the grounds that a debt older than the widest band would
otherwise show in no overdue tile at all — real, and still true. It went back
out because day-zero inclusion means a no-ceiling band always equals the sum
of every owed balance, which is Total receivable, one tile to its left. A
tile that cannot read differently from its neighbour is not carrying
information, so the gap it leaves — a balance over a month old shows in Total
receivable and nowhere in this row — is an accepted, knowing cost, not an
oversight.
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
        Balance report takes. `credit_period` is accepted (Customer Balance's
        own Debit/Credit split still reads it) but plays no part in these
        overdue bands — see test_credit_period_plays_no_part_in_overdue below.
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
        self.customer("Recent", 10000, days_standing=5)
        self.customer("Long overdue", 25000, days_standing=400)
        self.assertEqual(self.money("Total receivable"), "₹35,000")

    def test_each_band_runs_from_nought_up_to_its_own_limit(self):
        self.customer("Yesterday", 1000, days_standing=1)
        self.customer("Five days", 2000, days_standing=5)
        self.customer("Three weeks", 4000, days_standing=21)
        self.customer("Half a year", 8000, days_standing=180)
        self.assertEqual(self.money("Overdue 0-2 days"), "₹1,000")
        self.assertEqual(self.money("Overdue 0-7 days"), "₹3,000")
        # The half-year-old balance is past the widest band's own 30-day
        # ceiling, so — unlike Total receivable — it does not reach this figure.
        self.assertEqual(self.money("Overdue 0-1 month"), "₹7,000")
        self.assertEqual(self.money("Total receivable"), "₹15,000")

    def test_a_debt_older_than_every_band_is_invisible_to_all_of_them(self):
        """The accepted cost of having no no-ceiling band: a balance past the
        widest dated band's own limit shows in Total receivable and nowhere
        in this row. Real, and known — see the module docstring."""
        self.customer("Half a year", 8000, days_standing=180)
        self.assertEqual(self.money("Total receivable"), "₹8,000")
        for label in ("Overdue 0-2 days", "Overdue 0-7 days", "Overdue 0-1 month"):
            self.assertEqual(self.money(label), "₹0", label)

    def test_there_is_no_total_overdue_tile(self):
        """Dropped a second time, this time for good — see the module
        docstring for why a no-ceiling band cannot coexist with day-zero
        balances counting as overdue."""
        self.customer("Anything", 1000, days_standing=1)
        self.assertNotIn("Total overdue", self.stats())

    def test_a_balance_raised_today_counts_from_day_zero(self):
        """Money billed today is still money owed — it belongs in the
        narrowest band immediately rather than waiting a day to appear
        anywhere. The second failure these bands were rewritten for was a
        customer exactly one day late reading nought everywhere; the same
        principle now reaches back to day zero itself."""
        self.customer("Billed today", 24159, days_standing=0)
        self.customer("One day late", 2386, days_standing=1)
        for label in ("Overdue 0-2 days", "Overdue 0-7 days", "Overdue 0-1 month"):
            self.assertEqual(self.money(label), "₹26,545", label)
        self.assertEqual(self.stats()["Overdue 0-2 days"]["sub"], "2 customers")
        self.assertEqual(self.money("Total receivable"), "₹26,545")

    def test_the_bands_nest_rather_than_partition(self):
        """One balance two days late is inside every band, because every band
        starts at nought."""
        self.customer("Just late", 5000, days_standing=2)
        for label in ("Overdue 0-2 days", "Overdue 0-7 days", "Overdue 0-1 month"):
            self.assertEqual(self.money(label), "₹5,000", label)

    def test_credit_period_plays_no_part_in_overdue(self):
        """Fifteen days standing on a thirty-day credit period would once have
        read as not late at all — the excess past the agreed term was what
        counted. It now counts as fifteen days overdue regardless: inside the
        month and week bands, outside the two-day one, exactly as a customer
        with no credit period at fifteen days standing would."""
        self.customer("Generous terms", 9000, days_standing=15, credit_period=30)
        self.assertEqual(self.money("Total receivable"), "₹9,000")
        self.assertEqual(self.money("Overdue 0-1 month"), "₹9,000")
        self.assertEqual(self.money("Overdue 0-7 days"), "₹0")
        self.assertEqual(self.money("Overdue 0-2 days"), "₹0")

    def test_a_generous_credit_period_does_not_shift_the_window(self):
        """The window measures from the balance's own age, not from a due date
        computed off the credit period — a hundred-day credit period does not
        make a five-day-old balance read as brand new."""
        self.customer("Long credit", 6000, days_standing=5, credit_period=100)
        self.assertEqual(self.money("Overdue 0-7 days"), "₹6,000")
        self.assertEqual(self.money("Overdue 0-2 days"), "₹0")

    def test_a_customer_counts_once_and_the_card_says_how_many(self):
        self.customer("A", 1000, days_standing=3)
        self.customer("B", 1000, days_standing=4)
        self.assertEqual(self.stats()["Overdue 0-7 days"]["sub"], "2 customers")
        self.assertEqual(self.stats()["Overdue 0-2 days"]["sub"], "0 customers")

    def test_an_empty_band_is_not_dressed_up_as_a_problem(self):
        """Three days late is nothing to a month's band, and a red nought
        would read as a debt that is not there."""
        self.customer("Recent", 1000, days_standing=3)   # inside 0-7, not 0-2
        self.assertIsNone(self.stats()["Overdue 0-2 days"]["tone"])
        self.assertEqual(self.money("Overdue 0-2 days"), "₹0")

    def test_a_band_with_money_in_it_is_flagged(self):
        self.customer("Ancient", 1000, days_standing=10)
        self.assertEqual(self.stats()["Overdue 0-1 month"]["tone"], "bad")

    def test_a_customer_in_credit_is_not_receivable_at_all(self):
        """An advance is money we hold, not money we are owed."""
        c = Customer.objects.create(name="Paid ahead", credit_period=0,
                                    phone="9999999999", mobile="8999999999")
        SalesInvoice.objects.create(customer=c, date=self.today - timedelta(days=10),
                                    net_amount=Decimal("-4000"), is_active=True)
        self.assertEqual(self.money("Total receivable"), "₹0")
        self.assertEqual(self.money("Overdue 0-1 month"), "₹0")
