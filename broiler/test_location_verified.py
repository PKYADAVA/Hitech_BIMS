"""A pin recorded on a visit counts as verified.

``BroilerFarm.location_verified`` says "somebody has confirmed this pin is
where the farm is". Nothing ever set it: every farm read "Pin not verified"
for ever, the Verified state was unreachable, and the farm list, the Route
Planner and the farm report were all reporting a field with no writer.

A location capture is somebody standing at the farm writing down what their
phone says, so that is what sets it.
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from broiler.models import (Branch, BroilerFarm, Farmer, FarmLocationCapture,
                            Region, Supervisor)


class LocationVerifiedTests(TestCase):

    def setUp(self):
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Bahraich", region=region, prefix="BHR")
        supervisor = Supervisor.objects.create(branch=branch, name="R. Verma")
        self.user = get_user_model().objects.create_superuser("visitor", password="x")
        self.farm = BroilerFarm.objects.create(
            branch=branch, supervisor=supervisor,
            farmer=Farmer.objects.create(farmer_name="S. Yadav"),
            region=region.description, line="L1", farm_name="Yadav Farm",
            farm_capacity=900)

    def capture(self, **kw):
        return FarmLocationCapture.objects.create(
            farm=self.farm, date=date(2026, 8, 1), captured_by=self.user, **kw)

    def refreshed(self):
        self.farm.refresh_from_db()
        return self.farm

    def test_a_farm_starts_unverified(self):
        self.assertFalse(self.farm.location_verified)

    def test_a_capture_with_a_reading_verifies_the_pin(self):
        self.capture(latitude=26.7, longitude=82.1)
        farm = self.refreshed()
        self.assertTrue(farm.location_verified)
        self.assertEqual((farm.farm_latitude, farm.farm_longitude), (26.7, 82.1))

    def test_a_capture_with_no_reading_verifies_nothing(self):
        # A visit that recorded photos but never got a fix has confirmed
        # nothing about where the farm is.
        self.capture(address="Near the canal")
        self.assertFalse(self.refreshed().location_verified)

    def test_typing_coordinates_on_the_master_is_not_verification(self):
        # The distinction the flag exists to draw: a pin somebody typed in is
        # not a pin somebody stood on.
        self.farm.farm_latitude, self.farm.farm_longitude = 26.9, 82.4
        self.farm.save()
        self.assertFalse(self.refreshed().location_verified)

    def test_it_stays_verified_after_the_capture_is_deleted(self):
        # The visit still happened, whatever became of the paperwork.
        capture = self.capture(latitude=26.7, longitude=82.1)
        self.assertTrue(self.refreshed().location_verified)
        capture.delete()
        self.assertTrue(self.refreshed().location_verified)

    def test_a_later_capture_moves_the_pin_and_leaves_it_verified(self):
        self.capture(latitude=26.7, longitude=82.1)
        FarmLocationCapture.objects.create(
            farm=self.farm, date=date(2026, 9, 1), captured_by=self.user,
            latitude=26.8, longitude=82.2)
        farm = self.refreshed()
        self.assertEqual((farm.farm_latitude, farm.farm_longitude), (26.8, 82.2))
        self.assertTrue(farm.location_verified)

    def test_the_farm_list_reports_it(self):
        self.capture(latitude=26.7, longitude=82.1)
        self.client.force_login(self.user)
        row = next(r for r in self.client.get("/broiler_farm/").json()
                   if r["id"] == self.farm.id)
        self.assertTrue(row["location_verified"])
        self.assertTrue(row["has_location"])
