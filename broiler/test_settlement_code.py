"""The settlement's transaction number, after one has been deleted.

Reported: close a batch, delete the settlement, settle it again, and the number
is not the one that was freed — GCST-0005 is deleted and the replacement comes
out GCST-0006, with 0005 gone for good.

The cause was that the number was the primary key in disguise::

    self.settlement_code = f"GCST-{self.pk:04d}"

A key is never issued twice, so a deleted settlement took its number out of
circulation with it. That is the wrong shape for this document in particular:
deleting a settlement here *reopens the batch* to be settled again, so the
number has to come back with it. It also meant a rolled-back insert burned a
number, because the sequence advances either way.

It is minted from the highest in use now, which is how every other document in
this system is numbered — farm codes, batch numbers, the rest. So it refills
the number of a settlement that was the latest, and deliberately does not go
back for a gap in the middle.
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from broiler.models import (Branch, BroilerBatch, BroilerFarm, Farmer,
                            GrowingChargeSettlement, Region, Supervisor)


class SettlementCodeTests(TestCase):

    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.branch = Branch.objects.create(branch_name="Akbarpur",
                                            region=self.region, prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=self.branch, name="A. Pal")
        self.farmer = Farmer.objects.create(farmer_name="Vishvanath")
        self.farm = BroilerFarm.objects.create(
            branch=self.branch, supervisor=self.supervisor, farmer=self.farmer,
            region=self.region, line="Baskhari", farm_name="Vishvanath Farm",
            farm_capacity=5000)

    def settle(self, name):
        """Close one batch, and return its settlement."""
        batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name=name, book_number="BK-" + name,
            start_date=timezone.localdate() - timedelta(days=40))
        return GrowingChargeSettlement.objects.create(
            batch=batch, farm=self.farm, gc_date=timezone.localdate())

    def codes(self):
        return sorted(GrowingChargeSettlement.objects
                      .values_list("settlement_code", flat=True))

    # --- the ordinary run ------------------------------------------------

    def test_they_are_numbered_from_one(self):
        self.assertEqual(self.settle("B1").settlement_code, "GCST-0001")
        self.assertEqual(self.settle("B2").settlement_code, "GCST-0002")
        self.assertEqual(self.settle("B3").settlement_code, "GCST-0003")

    # --- the report ------------------------------------------------------

    def test_deleting_the_latest_frees_its_number(self):
        """The reported case. Deleting a settlement reopens its batch to be
        settled again, so the number it was using has to come back too."""
        self.settle("B1")
        self.settle("B2")
        latest = self.settle("B3")
        self.assertEqual(latest.settlement_code, "GCST-0003")

        latest.delete()

        self.assertEqual(self.settle("B3-again").settlement_code, "GCST-0003")

    def test_the_number_does_not_run_away_from_the_count(self):
        """Settle, delete and re-settle the same batch a few times over. The
        old behaviour climbed a number every round — five settlements and a
        code in the twenties."""
        self.settle("B1")
        for attempt in range(5):
            # A fresh batch each round: the batch is not what is being retried,
            # the numbering is. Batch names are unique per farm.
            self.settle("B2-try%d" % attempt).delete()
        self.assertEqual(self.settle("B2-final").settlement_code, "GCST-0002")

    def test_a_gap_in_the_middle_is_left_alone(self):
        """Highest-in-use plus one, not lowest-free. Deleting 0002 out of
        three does not send the next settlement back to fill it — the same
        rule as every other document number here."""
        self.settle("B1")
        middle = self.settle("B2")
        self.settle("B3")
        middle.delete()

        self.assertEqual(self.settle("B4").settlement_code, "GCST-0004")
        self.assertEqual(self.codes(), ["GCST-0001", "GCST-0003", "GCST-0004"])

    # --- what must not break ---------------------------------------------

    def test_two_settlements_never_share_a_number(self):
        made = [self.settle("B%d" % n).settlement_code for n in range(6)]
        self.assertEqual(len(set(made)), 6)

    def test_the_number_is_not_the_primary_key(self):
        """What it used to be, and the whole cause. A settlement whose row id
        has moved on must still take the next free number rather than its own
        id — otherwise deleting anything anywhere in the table pushes it."""
        first = self.settle("B1")
        first.delete()
        second = self.settle("B2")
        self.assertEqual(second.settlement_code, "GCST-0001")
        self.assertNotEqual(second.settlement_code, "GCST-%04d" % second.pk)

    def test_saving_an_existing_settlement_keeps_its_number(self):
        """Editing one must not reissue it. The number is on the farmer's
        printed statement."""
        s = self.settle("B1")
        s.remarks = "Corrected"
        s.save()
        s.refresh_from_db()
        self.assertEqual(s.settlement_code, "GCST-0001")
