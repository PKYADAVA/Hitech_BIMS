# pylint: disable=no-member
"""Tests for the customer-visit register, CRM linking, and master embed."""

import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from hr.models import Employee
from sales.models import Customer

from tracking.models import EmployeeCustomerVisit, TrackingLog, TrackingProvider
from tracking.services.sync_service import SyncService


class VisitApiTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")
        self.employee = Employee.objects.create(full_name="Sales Person")
        self.customer = Customer.objects.create(name="ACME Traders")
        self.today = timezone.localdate()
        now = timezone.now()
        self.matched = EmployeeCustomerVisit.objects.create(
            employee=self.employee, customer=self.customer,
            external_customer_name="ACME Traders",
            visit_date=self.today, status="completed",
            check_in_at=now - timedelta(hours=2), check_out_at=now - timedelta(hours=1),
            duration=timedelta(hours=1),
            check_in_latitude="26.85", check_in_longitude="80.95",
            next_follow_up=self.today,
        )
        self.unmatched = EmployeeCustomerVisit.objects.create(
            employee=self.employee, customer=None,
            external_customer_name="Acme Traders Pvt",
            visit_date=self.today, status="in_progress",
            check_in_at=now - timedelta(minutes=30),
        )

    def get_json(self, **params):
        response = self.client.get(reverse("api_tracking_visits"), params)
        return json.loads(response.content)

    def test_list_and_tiles(self):
        data = self.get_json()
        self.assertEqual(data["total"], 2)
        tiles = data["tiles"]
        self.assertEqual(tiles["completed"], 1)
        self.assertEqual(tiles["unmatched"], 1)
        self.assertEqual(tiles["unique_customers"], 1)
        self.assertEqual(tiles["avg_duration_min"], 60)
        self.assertEqual(tiles["follow_ups_due"], 1)

    def test_customer_filter_feeds_master_embed(self):
        data = self.get_json(customer=self.customer.pk)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["visits"][0]["customer"], "ACME Traders")

    def test_unmatched_filter(self):
        data = self.get_json(unmatched="1")
        self.assertEqual(data["total"], 1)
        self.assertFalse(data["visits"][0]["matched"])

    def test_date_and_search_filters(self):
        data = self.get_json(**{"from": (self.today + timedelta(days=1)).isoformat()})
        self.assertEqual(data["total"], 0)
        data = self.get_json(q="Acme Traders Pvt")
        self.assertEqual(data["total"], 1)

    def test_link_single_visit(self):
        response = self.client.post(
            reverse("api_tracking_visit_link"),
            json.dumps({"customer_id": self.customer.pk,
                        "visit_ids": [self.unmatched.pk]}),
            content_type="application/json",
        )
        data = json.loads(response.content)
        self.assertEqual(data["updated"], 1)
        self.unmatched.refresh_from_db()
        self.assertEqual(self.unmatched.customer, self.customer)
        self.assertTrue(TrackingLog.objects.filter(
            log_type="audit", event="mapping_changed").exists())

    def test_link_bulk_by_vendor_name(self):
        EmployeeCustomerVisit.objects.create(
            employee=self.employee, external_customer_name="Acme Traders Pvt",
            visit_date=self.today - timedelta(days=3),
            check_in_at=timezone.now() - timedelta(days=3),
        )
        response = self.client.post(
            reverse("api_tracking_visit_link"),
            json.dumps({"customer_id": self.customer.pk,
                        "external_customer_name": "acme traders pvt"}),
            content_type="application/json",
        )
        data = json.loads(response.content)
        self.assertEqual(data["updated"], 2)
        self.assertEqual(
            EmployeeCustomerVisit.objects.filter(customer__isnull=True).count(), 0)

    def test_link_requires_target(self):
        response = self.client.post(
            reverse("api_tracking_visit_link"),
            json.dumps({"customer_id": self.customer.pk}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_page_renders(self):
        response = self.client.get(reverse("tracking_visits"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer Visits")
        self.assertContains(response, "Link Visit to CRM Customer")


class VisitSyncFieldTests(TestCase):
    """Photo URL and follow-up flow from provider through to the table."""

    def test_sync_stores_photo_and_follow_up(self):
        TrackingProvider.objects.create(
            name="Mock", provider_type="mock", api_url="https://mock.invalid"
        )
        Employee.objects.create(full_name="Mock Employee One",
                                personal_contact=9000000001)
        SyncService(sleep=lambda seconds: None).sync_all(
            kinds=["employees", "visits"])
        visit = EmployeeCustomerVisit.objects.get()
        self.assertEqual(visit.photo_url, "https://mock.invalid/photos/visit-1.jpg")
        self.assertIsNotNone(visit.next_follow_up)


class CustomerMasterEmbedTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")
        Customer.objects.create(name="Embed Check Co")

    def test_customer_page_contains_visit_history_hook(self):
        response = self.client.get(reverse("customer"))
        self.assertEqual(response.status_code, 200)
        # Users with tracking access see the embed; markup is additive.
        self.assertContains(response, "view-visit-history")
        self.assertContains(response, "visitHistoryModal")
