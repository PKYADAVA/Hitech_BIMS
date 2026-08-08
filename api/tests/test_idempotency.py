"""A queued write is performed once, however many times the phone sends it.

The phone holds writes made with no signal and replays them on reconnect. From
the phone, a request that reached the server and was answered on a link that
died before the answer arrived is indistinguishable from one that never landed.
Replaying blind files the day twice — and a duplicated mortality figure moves
stock.
"""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from api.models import IdempotencyRecord
from broiler.models import Farmer

PATH = "/api/v1/broiler/farmers/"


class IdempotencyTests(TestCase):
    """Farmer is the subject only because it is the plainest write in the API:
    one required field, no stock movement, nothing to set up."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_superuser("idem", "i@x.com", "Str0ngPass!")
        self.other = User.objects.create_superuser("idem2", "i2@x.com", "Str0ngPass!")

    def auth(self, user=None):
        token = RefreshToken.for_user(user or self.user).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def post(self, name, key=None, user=None):
        headers = self.auth(user)
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        return self.client.post(PATH, data=json.dumps({"farmer_name": name}),
                                content_type="application/json", **headers)

    # ---- the guarantee -----------------------------------------------------

    def test_the_same_key_twice_creates_one_farmer(self):
        first = self.post("S. Yadav", key="abc-123")
        second = self.post("S. Yadav", key="abc-123")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Farmer.objects.filter(farmer_name="S. Yadav").count(), 1)

    def test_the_replay_returns_the_first_answer(self):
        # The phone needs the created row's id to attach photos to it. Handing
        # back an empty 201 would leave the follow-up write with nothing to
        # point at.
        first = self.post("R. Singh", key="abc-456")
        second = self.post("R. Singh", key="abc-456")
        self.assertEqual(second.content, first.content)
        self.assertEqual(second["Idempotent-Replay"], "true")

    def test_a_different_key_is_a_different_write(self):
        self.post("A. Kumar", key="k1")
        self.post("A. Kumar", key="k2")
        self.assertEqual(Farmer.objects.filter(farmer_name="A. Kumar").count(), 2)

    def test_no_key_is_left_alone(self):
        # The web ERP sends no key and must keep behaving exactly as it did.
        self.post("B. Lal")
        self.post("B. Lal")
        self.assertEqual(Farmer.objects.filter(farmer_name="B. Lal").count(), 2)
        self.assertFalse(IdempotencyRecord.objects.exists())

    def test_one_users_key_cannot_be_replayed_by_another(self):
        # Keys are client-generated, so without scoping a guessed one would
        # hand back another user's response — rows their scope may never allow.
        mine = self.post("C. Devi", key="shared-key")
        theirs = self.post("D. Prasad", key="shared-key", user=self.other)
        self.assertEqual(theirs.status_code, 201)
        self.assertNotEqual(theirs.content, mine.content)
        self.assertTrue(Farmer.objects.filter(farmer_name="D. Prasad").exists())

    # ---- what is worth remembering -----------------------------------------

    def test_a_rejected_payload_is_remembered(self):
        # A 400 is a verdict on the payload; it will not come out differently
        # on a retry, and re-running the validation buys nothing.
        first = self.post("", key="bad-1")
        self.assertEqual(first.status_code, 400)
        second = self.post("", key="bad-1")
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second["Idempotent-Replay"], "true")

    def test_a_key_still_running_asks_the_phone_to_come_back(self):
        # A retry fired while the first attempt is still climbing a slow link.
        # Answering it with a half-written record would be worse than waiting.
        IdempotencyRecord.objects.create(key="inflight", user=self.user,
                                         method="POST", path=PATH)
        response = self.post("E. Ram", key="inflight")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.content)["error"]["code"],
                         "idempotency_in_progress")
        self.assertFalse(Farmer.objects.filter(farmer_name="E. Ram").exists())

    def test_a_crashed_write_leaves_the_key_usable(self):
        # A 5xx may well have left nothing behind, so the key has to become
        # usable again — otherwise one server error locks it into "still
        # running" for ever and the phone can never file that entry at all.
        # The API turns an unhandled exception into a 500 rather than letting
        # it escape, so that is the path this takes.
        from unittest.mock import patch

        # The viewsets are generated by register_model, so there is no named
        # class to patch — the model's own save is the reachable seam.
        with patch("broiler.models.Farmer.save", side_effect=RuntimeError("boom")):
            crashed = self.post("F. Kumar", key="crash-1")
        self.assertEqual(crashed.status_code, 500)
        self.assertFalse(IdempotencyRecord.objects.filter(key="crash-1").exists())

        retry = self.post("F. Kumar", key="crash-1")
        self.assertEqual(retry.status_code, 201)
        self.assertNotIn("Idempotent-Replay", retry)
