"""Numbers the system mints for itself cannot repeat.

Four identifiers are generated rather than typed — a customer code, a supplier
code, a shed's unit number within its farm, and a hatch setting's batch/flock
number. Each is minted as "read the highest, add one", which is safe until two
saves read that highest in the same moment. Nothing in the schema stopped the
result, so a code that identified two records identified neither.

Each constraint is partial, and that is not decoration. A blank code is
allowed, and Postgres treats '' as a value rather than as an absence — a plain
unique index would admit the first blank row and refuse every one after it. In
the hatch setting's case that would be fatal to the ordinary path, because the
column is written empty by the first save and filled by a second.
"""
import importlib

from django.apps import apps as app_registry
from django.db import IntegrityError, transaction
from django.test import TestCase

from broiler.models import (Branch, BroilerFarm, BroilerFarmShed, BroilerLine,
                            Farmer, Region, Supervisor)
from purchase.models import Supplier
from sales.models import Customer


class MintedCodeTests(TestCase):
    """The two party codes, which share a shape."""

    def test_a_customer_code_cannot_be_taken_twice(self):
        Customer.objects.create(name="First", mobile="9990001111", address="A")
        held = Customer.objects.get(name="First").code
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Customer.objects.create(name="Second", mobile="9990002222",
                                        address="B", code=held)

    def test_a_supplier_code_cannot_be_taken_twice(self):
        Supplier.objects.create(name="First")
        held = Supplier.objects.get(name="First").code
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Supplier.objects.create(name="Second", code=held)

    def test_ordinary_saving_still_mints_a_fresh_code_each_time(self):
        """The constraint has to be invisible in normal use."""
        a = Customer.objects.create(name="A", mobile="9990001111", address="A")
        b = Customer.objects.create(name="B", mobile="9990002222", address="B")
        self.assertNotEqual(a.code, b.code)
        self.assertTrue(a.code.startswith("CUST-"))

    def test_more_than_one_party_may_have_no_code_at_all(self):
        """Why the constraint is partial. Postgres treats '' as a value, so a
        plain unique index would admit one blank row and refuse every one
        after it.

        Written through bulk_create because save() mints a code whenever it
        finds none — a blank can only reach the table by a path that skips it,
        which is exactly the legacy and bulk data the condition is there for.
        """
        Customer.objects.bulk_create([
            Customer(name="A", mobile="9990001111", address="A", code=""),
            Customer(name="B", mobile="9990002222", address="B", code=""),
        ])
        self.assertEqual(Customer.objects.filter(code="").count(), 2)


class ShedUnitNumberTests(TestCase):
    """A shed's number runs within its farm, so the rule does too."""

    def setUp(self):
        region = Region.objects.create(code="R1", description="East")
        self.branch = Branch.objects.create(code="B1", branch_name="Akbarpur",
                                            region=region)
        common = dict(branch=self.branch, region=region,
                      supervisor=Supervisor.objects.create(branch=self.branch,
                                                           name="S. Kumar"),
                      line=BroilerLine.objects.create(description="L1", region=region,
                                                      branch=self.branch),
                      farmer=Farmer.objects.create(farmer_name="Abhishek Kumar Singh"),
                      farm_capacity=5000)
        self.farm = BroilerFarm.objects.create(farm_name="Akbarpur Farm", **common)
        self.other_farm = BroilerFarm.objects.create(farm_name="Bahraich Farm", **common)

    def test_sheds_on_one_farm_are_numbered_in_sequence(self):
        first = BroilerFarmShed.objects.create(farm=self.farm)
        second = BroilerFarmShed.objects.create(farm=self.farm)
        self.assertEqual([first.unit_no, second.unit_no], [1, 2])

    def test_the_database_refuses_two_of_the_same_shed_number_on_a_farm(self):
        """Tested through bulk_create because a save cannot show it any more:
        the retry catches the clash and reissues, which is the point."""
        BroilerFarmShed.objects.create(farm=self.farm)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BroilerFarmShed.objects.bulk_create([
                    BroilerFarmShed(farm=self.farm, unit_no=1, shed_code="SHD-Z1")])

    def test_a_shed_whose_number_was_taken_is_given_the_next_one(self):
        """What a person sees instead of the refusal above. unit_no is not
        editable and nobody chooses it, so reissuing is not overriding an
        intention — it is finishing the job the save started."""
        first = BroilerFarmShed.objects.create(farm=self.farm)
        second = BroilerFarmShed.objects.create(farm=self.farm, unit_no=first.unit_no)
        self.assertEqual(first.unit_no, 1)
        self.assertEqual(second.unit_no, 2)
        self.assertEqual(BroilerFarmShed.objects.filter(farm=self.farm).count(), 2)

    def test_every_farm_has_its_own_shed_one(self):
        """Scoped to the farm, not global — the whole point. Shed 1 exists on
        every farm and always should."""
        here = BroilerFarmShed.objects.create(farm=self.farm)
        there = BroilerFarmShed.objects.create(farm=self.other_farm)
        self.assertEqual(here.unit_no, there.unit_no)

    def test_unnumbered_sheds_do_not_clash_with_each_other(self):
        """0 is the field's default, meaning "never went through save()".
        Several of those are not a clash, which is why 0 is excluded."""
        # shed_code is unique and also filled by save(), so a bulk insert has
        # to supply its own — the same '' trap in a column this change does
        # not touch.
        BroilerFarmShed.objects.bulk_create([
            BroilerFarmShed(farm=self.farm, unit_no=0, shed_code="SHD-X1"),
            BroilerFarmShed(farm=self.farm, unit_no=0, shed_code="SHD-X2"),
        ])
        self.assertEqual(BroilerFarmShed.objects.filter(unit_no=0).count(), 2)


def _renumber():
    """The migration's own function, imported by name.

    Tested directly rather than by running the migration: this is the step that
    decides whether the deploy carrying the constraint succeeds, and it has to
    be exercised against data that actually clashes — which the migration
    cannot be handed once the constraint exists.
    """
    module = importlib.import_module(
        "sales.migrations.0018_customer_unique_customer_code")
    return module.renumber_duplicate_codes


class DeduplicationTests(TestCase):
    """The migration's renumbering step, which decides whether the deploy that
    carries these constraints succeeds at all.

    The constraint is dropped for the duration of each test, because that is
    the state the step actually runs in — the migration renumbers first and
    creates the constraint after. Trying to stage a clash against a table that
    already refuses one would only prove the constraint works.
    """

    def setUp(self):
        from django.db import connection

        # Dropped, not restored: DDL is transactional in Postgres and this
        # runs inside the test's own transaction, so the index comes back when
        # the test rolls back. Adding it again by hand fails anyway — the
        # table has pending trigger events from the rows just written.
        with connection.schema_editor(atomic=False) as editor:
            editor.remove_constraint(Customer, Customer._meta.constraints[0])

    def test_a_repeated_code_is_given_the_next_free_one(self):
        Customer.objects.create(name="A", mobile="9990001111", address="A")
        Customer.objects.create(name="B", mobile="9990002222", address="B")
        # Force the clash the constraint would refuse, the way concurrency
        # would have produced it.
        Customer.objects.filter(name="B").update(code="CUST-0001")
        Customer.objects.filter(name="A").update(code="CUST-0001")

        _renumber()(app_registry, None)

        codes = sorted(Customer.objects.values_list("code", flat=True))
        self.assertEqual(len(set(codes)), 2, codes)

    def test_the_oldest_record_keeps_the_code(self):
        """Whoever has had it longest is the one it is already printed on."""
        first = Customer.objects.create(name="A", mobile="9990001111", address="A")
        second = Customer.objects.create(name="B", mobile="9990002222", address="B")
        Customer.objects.filter(pk__in=[first.pk, second.pk]).update(code="CUST-0001")

        _renumber()(app_registry, None)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.code, "CUST-0001")
        self.assertNotEqual(second.code, "CUST-0001")

    def test_renumbering_a_clean_database_changes_nothing(self):
        """Which is the case on every database we can see, so it had better
        be a no-op rather than a reshuffle."""
        Customer.objects.create(name="A", mobile="9990001111", address="A")
        Customer.objects.create(name="B", mobile="9990002222", address="B")
        before = dict(Customer.objects.values_list("id", "code"))

        _renumber()(app_registry, None)

        self.assertEqual(dict(Customer.objects.values_list("id", "code")), before)


class MintingRetryTests(TestCase):
    """What happens to the save that loses the race.

    A unique index turns a silent duplicate into a refusal, which is the right
    trade only if the refusal is not what the user sees. The loser re-reads the
    highest code and takes the next one — which is what would have happened had
    the two saves arrived one after the other instead of together.
    """

    def test_a_save_whose_code_was_taken_still_lands(self):
        first = Customer.objects.create(name="A", mobile="9990001111", address="A")

        # Stand in for the other save: the moment this one has minted its code
        # and is about to write, someone else takes it.
        taken = {"done": False}
        original = Customer.next_code.__func__

        def steal(cls):
            code = original(cls)
            if not taken["done"]:
                taken["done"] = True
                # Give the code away to a record written behind this one's back.
                Customer.objects.filter(pk=first.pk).update(code=code)
            return code

        Customer.next_code = classmethod(steal)
        try:
            second = Customer.objects.create(name="B", mobile="9990002222",
                                             address="B")
        finally:
            Customer.next_code = classmethod(original)

        self.assertTrue(taken["done"], "the race was never staged")
        first.refresh_from_db()
        self.assertNotEqual(second.code, first.code)
        self.assertEqual(Customer.objects.count(), 2)

    def test_it_gives_up_rather_than_looping_for_ever(self):
        """A failure that is not a clash must come straight out — a missing
        foreign key will not fix itself on the second attempt."""
        from django.db import IntegrityError

        from Hitech_BIMS.minting import mint_with_retry

        attempts = []

        def write():
            attempts.append(1)
            raise IntegrityError("null value in column violates not-null")

        with self.assertRaises(IntegrityError):
            mint_with_retry(write, lambda: None, attempts=5)
        self.assertEqual(len(attempts), 1)

    def test_a_clash_is_retried_a_bounded_number_of_times(self):
        from django.db import IntegrityError

        from Hitech_BIMS.minting import is_unique_violation, mint_with_retry

        self.assertTrue(is_unique_violation(
            IntegrityError("duplicate key value violates unique constraint")))
        attempts = []

        def always_clashes():
            attempts.append(1)
            raise IntegrityError("duplicate key value violates unique constraint")

        with self.assertRaises(IntegrityError):
            mint_with_retry(always_clashes, lambda: None, attempts=3)
        self.assertEqual(len(attempts), 3)
