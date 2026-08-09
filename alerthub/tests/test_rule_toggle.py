"""Turning a watch on or off from the list.

Switching an alert off is the edit made in a hurry — usually while it is still
firing at two in the morning — and it used to mean opening the form, finding
one checkbox among a dozen fields and saving.
"""
import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from alerthub.models import AlertRule


class AlertRuleToggleTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.user = User.objects.create_superuser("alerter", "a@x.com", "Str0ngPass!")
        self.client.force_login(self.user)
        # A rule whose alert type the catalogue actually supports, so the
        # "cannot fire" guard is not what is under test here.
        self.rule = AlertRule.objects.create(
            name="High Mortality — test", module="production",
            rule_key="production.high_mortality", priority="critical",
            operator="gte", threshold=10, is_active=False)

    def toggle(self, rule=None):
        return self.client.post(
            reverse("alerthub:alert_rule_toggle", args=[(rule or self.rule).pk]))

    def test_one_post_flips_it(self):
        before = self.rule.is_active
        response = self.toggle()
        self.assertEqual(response.status_code, 200)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.is_active, not before)

    def test_the_answer_says_where_it_ended_up(self):
        # The switch is flipped optimistically and corrected from this, so a
        # response that did not say would leave the screen guessing.
        body = json.loads(self.toggle().content)
        self.rule.refresh_from_db()
        self.assertEqual(body["is_active"], self.rule.is_active)
        self.assertIn(self.rule.name, body["message"])

    def test_toggling_twice_returns_it(self):
        before = self.rule.is_active
        self.toggle()
        self.toggle()
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.is_active, before)

    def test_a_get_changes_nothing(self):
        # A link that changes state is one a browser or a crawler follows on
        # its own, and "something disabled our alerts" is a bad afternoon.
        before = self.rule.is_active
        response = self.client.get(
            reverse("alerthub:alert_rule_toggle", args=[self.rule.pk]))
        self.assertEqual(response.status_code, 405)
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.is_active, before)

    def test_a_stranger_cannot_toggle(self):
        self.client.logout()
        before = self.rule.is_active
        self.toggle()
        self.rule.refresh_from_db()
        self.assertEqual(self.rule.is_active, before)

    def test_a_rule_with_no_data_source_cannot_be_switched_on(self):
        # It could never fire, so an Enabled badge on it would mean nothing.
        orphan = AlertRule.objects.create(
            name="Invented alert", module="production",
            rule_key="production.not_a_real_key",
            priority="medium", operator="gte", threshold=1, is_active=False)
        response = self.toggle(orphan)
        self.assertEqual(response.status_code, 400)
        orphan.refresh_from_db()
        self.assertFalse(orphan.is_active)

    def test_but_such_a_rule_can_still_be_switched_off(self):
        # Whatever left it enabled, refusing to let anyone turn it off would
        # trap it in a state nobody can leave.
        orphan = AlertRule.objects.create(
            name="Invented alert", module="production",
            rule_key="production.not_a_real_key",
            priority="medium", operator="gte", threshold=1, is_active=True)
        self.assertEqual(self.toggle(orphan).status_code, 200)
        orphan.refresh_from_db()
        self.assertFalse(orphan.is_active)

    def test_the_list_offers_the_switch(self):
        html = self.client.get(reverse("alerthub:alert_rule_list")).content.decode()
        self.assertIn("ah-toggle", html)
        self.assertIn(
            reverse("alerthub:alert_rule_toggle", args=[self.rule.pk]), html)
        # Without a token on the page the POST would be rejected, and the
        # switch would fail for everyone.
        self.assertIn("csrfmiddlewaretoken", html)
