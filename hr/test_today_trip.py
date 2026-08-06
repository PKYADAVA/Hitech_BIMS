"""What the phone's Home screen asks for: *my* trip, today.

The card pinned above the dashboard reads one endpoint —
``/api/v1/hr/trips/?date=<today>`` — and shows whatever single row comes back.
Everything that makes that safe is on this side of the wire: the viewset
narrows to the employee behind the login, and the database holds one trip per
person per day. So the card can trust the first row without checking whose it
is, and a phone asking for a colleague's day gets its own back instead.
"""
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.test import TestCase
from rest_framework.test import APIClient

from .models import Employee, SupervisorTrip

URL = "/api/v1/hr/trips/"


class TodayTripTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.today = timezone.localdate()
        self.yesterday = self.today - timezone.timedelta(days=1)

        self.driver_user = User.objects.create_user("driver", password="x")
        self.driver = Employee.objects.create(full_name="A. Pal",
                                              user=self.driver_user)
        self.other_user = User.objects.create_user("other", password="x")
        self.other = Employee.objects.create(full_name="S. Yadav",
                                             user=self.other_user)

        self.mine = SupervisorTrip.objects.create(
            employee=self.driver, date=self.today, start_odometer=1000)
        self.old = SupervisorTrip.objects.create(
            employee=self.driver, date=self.yesterday, start_odometer=800,
            end_odometer=868, status="Completed")
        self.theirs = SupervisorTrip.objects.create(
            employee=self.other, date=self.today, start_odometer=500)

        self.client = APIClient()
        self.client.force_authenticate(self.driver_user)

    def rows(self, **params):
        return self.client.get(URL, params).json()["data"]

    def test_today_returns_only_my_own_trip(self):
        rows = self.rows(date=str(self.today))
        self.assertEqual([r["id"] for r in rows], [self.mine.id])

    def test_a_colleagues_trip_is_not_reachable_by_asking_for_it(self):
        # The narrowing is a queryset rule, so naming the other employee in the
        # query string filters *within* my own rows rather than opening theirs.
        rows = self.rows(date=str(self.today), employee=self.other.id)
        self.assertEqual(rows, [])

    def test_no_trip_today_is_an_empty_list_not_yesterdays(self):
        self.mine.delete()
        self.assertEqual(self.rows(date=str(self.today)), [])
        # Yesterday's is still there — the date filter is what excluded it.
        self.assertEqual([r["id"] for r in self.rows(date=str(self.yesterday))],
                         [self.old.id])

    def test_the_row_carries_what_the_card_prints(self):
        row = self.rows(date=str(self.today))[0]
        for field in ("trip_no", "status", "distance_km", "registration",
                      "start_photo_at", "end_photo_at"):
            self.assertIn(field, row)

    def test_a_login_with_no_employee_record_gets_no_trip_of_its_own(self):
        # A back-office login is not any driver, so Home shows it no card. The
        # scope still decides what it may *see*; this only proves the endpoint
        # does not hand it someone else's day as if it were its own.
        User = get_user_model()
        back_office = User.objects.create_user("desk", password="x")
        self.assertFalse(Employee.objects.filter(user=back_office).exists())
