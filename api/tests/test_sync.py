"""Two people counting the same shed, and the monitor that shows unsent work.

A supervisor records ten dead birds in Shed 2 on the 8th. By the time their
phone finds signal the office has already entered seven for the same day. Both
are somebody's count. Taking the newer one means taking whichever handset found
signal last, and losing a real number without telling anybody.
"""
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import DeviceSyncState
from broiler.models import (Branch, BroilerBatch, BroilerFarm, DailyEntry,
                            Farmer, Region, Supervisor)

ENTRIES = "/api/v1/broiler/daily-entries/"
HEARTBEAT = "/api/v1/sync/heartbeat"


class SyncConflictTests(TestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        region = Region.objects.create(description="East")
        branch = Branch.objects.create(branch_name="Akbarpur", region=region, prefix="AKB")
        self.supervisor = Supervisor.objects.create(branch=branch, name="R. Singh")
        self.farm = BroilerFarm.objects.create(
            branch=branch, farmer=Farmer.objects.create(farmer_name="S. Yadav"),
            region=region, line="L1", supervisor=self.supervisor,
            farm_name="Mineglade", farm_capacity=5000)
        self.batch = BroilerBatch.objects.create(
            broiler_farm=self.farm, batch_name="BR24001",
            start_date=self.today - timedelta(days=20))

        User = get_user_model()
        self.user = User.objects.create_superuser("syncer", "s@x.com", "Str0ngPass!")

    def auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(self.user).access_token}"}

    def post_entry(self, mortality, **extra):
        body = {"farm": self.farm.id, "batch": self.batch.id,
                "date": self.today.isoformat(), "supervisor": self.supervisor.id,
                "mortality": mortality, **extra}
        return self.client.post(ENTRIES, data=json.dumps(body),
                                content_type="application/json", **self.auth())

    # ---- the rule ----------------------------------------------------------

    def test_a_second_count_for_the_same_day_is_refused_not_applied(self):
        self.assertEqual(self.post_entry(7).status_code, 201)
        clash = self.post_entry(10)
        self.assertEqual(clash.status_code, 409)
        body = json.loads(clash.content)
        self.assertEqual(body["error"]["code"], "sync_conflict")
        # Only one row: the office's figure stands until somebody decides.
        self.assertEqual(DailyEntry.objects.filter(date=self.today).count(), 1)
        self.assertEqual(DailyEntry.objects.get(date=self.today).mortality, 7)

    def test_the_refusal_carries_both_figures(self):
        # The phone has to show them side by side; a bare 409 would leave the
        # supervisor guessing what they are choosing between.
        self.post_entry(7)
        body = json.loads(self.post_entry(10).content)
        fields = body["error"]["conflict"]["fields"]
        mortality = [f for f in fields if f["field"] == "mortality"][0]
        self.assertEqual(mortality["server"], "7")
        self.assertEqual(mortality["local"], "10")

    def test_the_same_figure_twice_is_not_a_conflict(self):
        # Two phones agreeing is not a disagreement. The idempotency key
        # handles the true duplicate; this is about a genuinely second write.
        self.post_entry(7)
        self.assertNotEqual(self.post_entry(7).status_code, 409)

    def test_a_different_day_is_not_a_conflict(self):
        self.post_entry(7)
        body = {"farm": self.farm.id, "batch": self.batch.id,
                "date": (self.today - timedelta(days=1)).isoformat(),
                "supervisor": self.supervisor.id, "mortality": 10}
        response = self.client.post(ENTRIES, data=json.dumps(body),
                                    content_type="application/json", **self.auth())
        self.assertEqual(response.status_code, 201)

    def test_the_user_can_insist(self):
        # "Accept mine" in the Sync Center: they have seen both figures and
        # chosen. Refusing again would leave no way through.
        self.post_entry(7)
        forced = self.post_entry(10, __resolve_conflict="accept_offline")
        self.assertEqual(forced.status_code, 201)


class SyncHeartbeatTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_user("beater", "b@x.com", "Str0ngPass!")

    def auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(self.user).access_token}"}

    def beat(self, **over):
        body = {"device_id": "Nokia G21 (a1b2c3)", "pending": 7,
                "failed": 1, "conflicts": 0, "synced": 142, **over}
        return self.client.post(HEARTBEAT, data=json.dumps(body),
                                content_type="application/json", **self.auth())

    def test_a_device_reports_what_it_is_holding(self):
        self.assertEqual(self.beat().status_code, 200)
        state = DeviceSyncState.objects.get(user=self.user)
        self.assertEqual((state.pending, state.failed, state.synced), (7, 1, 142))

    def test_reporting_again_replaces_rather_than_accumulates(self):
        # A snapshot, not a log: the office wants what is outstanding now, and
        # a row per heartbeat would bury it.
        self.beat()
        self.beat(pending=0, failed=0)
        self.assertEqual(DeviceSyncState.objects.filter(user=self.user).count(), 1)
        self.assertEqual(DeviceSyncState.objects.get(user=self.user).pending, 0)

    def test_two_phones_are_two_rows(self):
        self.beat()
        self.beat(device_id="Redmi 12 (d4e5f6)")
        self.assertEqual(DeviceSyncState.objects.filter(user=self.user).count(), 2)

    def test_a_stranger_cannot_report(self):
        response = self.client.post(HEARTBEAT, data=json.dumps({"device_id": "x"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_work_left_too_long_is_flagged(self):
        # A round still unsent after half a day is no longer "walking back".
        self.beat(oldest_pending_at=(timezone.now() - timedelta(hours=20)).isoformat())
        self.assertTrue(DeviceSyncState.objects.get(user=self.user).is_stuck)

    def test_a_quiet_device_is_not_flagged_as_stuck(self):
        self.beat(pending=0, failed=0, oldest_pending_at=None)
        state = DeviceSyncState.objects.get(user=self.user)
        self.assertFalse(state.is_stuck)
        self.assertFalse(state.needs_attention)


class SyncMonitorPageTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("mon", "m@x.com", "Str0ngPass!")
        self.client.force_login(self.admin)

    def test_the_monitor_lists_a_reporting_device(self):
        DeviceSyncState.objects.create(user=self.admin, device_id="Nokia G21",
                                       pending=7, failed=1)
        html = self.client.get(reverse("offline_sync_monitor")).content.decode()
        self.assertIn("Nokia G21", html)
        self.assertIn("Offline Sync Monitor", html)

    def test_it_says_so_plainly_when_no_phone_has_reported(self):
        # An empty table with no explanation reads as a broken page.
        html = self.client.get(reverse("offline_sync_monitor")).content.decode()
        self.assertIn("No phone has reported yet", html)
