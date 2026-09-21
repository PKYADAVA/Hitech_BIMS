# -*- coding: utf-8 -*-
"""Room left in a shared unit, as the placement screen asks for it."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from inventory.models import Item, ItemCategory, StockTransfer, Warehouse

from .models import (Branch, Breed, BroilerBatch, BroilerFarm, BroilerFarmShed,
                     DailyEntry, Farmer, Region, Supervisor)


class ShedHeadroomTests(TestCase):
    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region,
                                       prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.farm = BroilerFarm.objects.create(
            branch=branch, region=region, supervisor=self.supervisor,
            farmer=Farmer.objects.create(farmer_name="S. Yadav"),
            line="L1", farm_name="Yadav Farm", farm_capacity=9000)
        self.shed = BroilerFarmShed.objects.create(
            farm=self.farm, shed_name="Shed A", capacity=6000)
        self.breed = Breed.objects.create(code="COBB", description="Cobb 500")
        self.store = Warehouse.objects.create(name="Akbarpur Warehouse")
        self.chick = Item.objects.create(
            description="Day Old Chick", standard_cost_per_unit=30,
            category=ItemCategory.objects.create(name="Day Old Chicks"),
            valuation_method="Weighted Average", usage="Produced",
            source="Purchased", type="Raw Material", item_account="Expense")
        self.user = get_user_model().objects.create_superuser("u", password="x")
        self.client.force_login(self.user)

    def batch(self):
        return BroilerBatch.objects.create(broiler_farm=self.farm, shed=self.shed,
                                           breed=self.breed, start_date=date.today())

    def ask(self, batch):
        return self.client.get(f"/broiler_batch/{batch.id}/shed-headroom/").json()

    def place(self, batch, birds):
        """Birds in the shed, as a placement puts them there."""
        StockTransfer.objects.create(
            date=date.today(), item=self.chick, quantity=birds, rate=30,
            from_location_type="warehouse", from_warehouse=self.store,
            to_location_type="farm", to_farm=self.farm, to_batch=batch)

    def test_an_empty_unit_offers_all_of_it(self):
        row = self.ask(self.batch())
        self.assertEqual((row["capacity"], row["in_shed"], row["headroom"]),
                         (6000, 0, 6000))

    def test_a_unit_with_no_capacity_says_nothing(self):
        self.shed.capacity = 0
        self.shed.save()
        self.assertIsNone(self.ask(self.batch())["capacity"])

    def test_a_flock_already_in_there_takes_its_room(self):
        first = self.batch()
        self.place(first, 4000)
        self.assertEqual(self.ask(self.batch())["headroom"], 2000)

    def test_every_open_flock_in_the_unit_counts(self):
        # The point of the endpoint: a second flock sharing the shed is
        # taking room the third one cannot have.
        first, second = self.batch(), self.batch()
        self.place(first, 3000)
        self.place(second, 2000)
        row = self.ask(self.batch())
        self.assertEqual((row["in_shed"], row["headroom"]), (5000, 1000))

    def test_birds_that_died_are_not_still_taking_room(self):
        first = self.batch()
        self.place(first, 4000)
        DailyEntry.objects.create(farm=self.farm, batch=first, date=date.today(),
                                  supervisor=self.supervisor,
                                  mortality=500, culls=100)
        row = self.ask(self.batch())
        self.assertEqual((row["in_shed"], row["headroom"]), (3400, 2600))

    def test_a_settled_flock_leaves_the_unit(self):
        first = self.batch()
        self.place(first, 4000)
        BroilerBatch.objects.filter(id=first.id).update(is_closed=True)
        self.assertEqual(self.ask(self.batch())["headroom"], 6000)
