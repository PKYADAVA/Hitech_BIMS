"""The phone's way into the approval queue.

The register on the phone offers "Request Edit" and "Request Deletion" to a
user who may look at a module but not change it. Both go through
/api/v1/hatchery/change-requests/create, and the whole feature rests on one
unobvious property of that endpoint: it checks the *view* right, not the edit
or delete right. Checking the right the user is missing would refuse every
request the feature exists to raise.

The endpoint had no tests. These pin the permission rule at both ends, and the
round trip — that what the phone proposes is what an approval writes — because
a payload stored in one shape and replayed in another would corrupt a record
with a reviewer's signature on it.
"""
from datetime import date

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from hatchery.models import ChangeRequest

CREATE = "/api/v1/hatchery/change-requests/create"


class MobileChangeRequestAPITestCase(APITestCase):
    """A farm location capture: a flat record whose save reads the same field
    names the phone's form submits, which is what makes it proposable at all.
    A module whose correction cannot be expressed as one payload does not
    appear on this route in the first place."""

    MODULE = "farm_location_capture"
    TAB = "farm_location_capture_list"

    def setUp(self):
        from broiler.models import (Branch, BroilerFarm, BroilerLine, Farmer,
                                    FarmLocationCapture, Region, Supervisor)

        region = Region.objects.create(code="R1", description="East")
        branch = Branch.objects.create(code="B1", branch_name="Akbarpur", region=region)
        self.farm = BroilerFarm.objects.create(
            farm_name="Akbarpur Farm", branch=branch, region=region,
            supervisor=Supervisor.objects.create(branch=branch, name="S. Kumar"),
            line=BroilerLine.objects.create(description="Line 1", region=region,
                                            branch=branch),
            farmer=Farmer.objects.create(farmer_name="Abhishek Kumar Singh"),
            farm_capacity=5000)
        self.record = FarmLocationCapture.objects.create(
            farm=self.farm, date=date(2026, 7, 2), district="Ambedkar Nagar")

        self.viewer = get_user_model().objects.create_user(
            username="supervisor", password="x", email="s@example.com")
        self.client.force_authenticate(self.viewer)

    def grant(self, user, tab, **actions):
        """Give a user a matrix of their own. An account with no configuration
        is unrestricted by design, so a test that skips this is testing the
        superuser path by accident."""
        from user.models import UserProfile, UserTabPermission

        UserProfile.objects.update_or_create(
            user=user, defaults={"individual_permissions": True})
        UserTabPermission.objects.update_or_create(
            user=user, tab_code=tab,
            defaults={"can_view": True, **actions})

    def payload(self, **overrides):
        fields = {
            "farm": self.farm.id, "date": "2026-07-02",
            "district": "Ambedkar Nagar", "state": "Uttar Pradesh",
        }
        fields.update(overrides)
        return fields

    def request_edit(self, **overrides):
        return self.client.post(CREATE, {
            "module": self.MODULE, "object_id": self.record.id,
            "action": "edit", "payload": self.payload(**overrides),
        }, format="json")


class EditRequestPermissionTests(MobileChangeRequestAPITestCase):

    def test_a_user_who_may_only_look_can_still_propose_a_correction(self):
        """The rule the whole feature rests on. Testing the edit right here
        would refuse exactly the people this is for."""
        self.grant(self.viewer, self.TAB, can_edit=False, can_delete=False)
        resp = self.request_edit(district="Faizabad")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(ChangeRequest.objects.count(), 1)

    def test_the_record_is_untouched_until_someone_approves(self):
        """A proposal that quietly wrote through would be an edit right handed
        out by the back door."""
        self.grant(self.viewer, self.TAB, can_edit=False)
        self.request_edit(district="Faizabad")
        self.record.refresh_from_db()
        self.assertEqual(self.record.district, "Ambedkar Nagar")

    def test_someone_with_no_access_to_the_module_is_refused(self):
        """View is the floor, not a formality — otherwise the queue becomes a
        way to reach a module you cannot open."""
        self.grant(self.viewer, "daily_entry_list")     # some other tab
        self.assertEqual(self.request_edit().status_code, 403)
        self.assertEqual(ChangeRequest.objects.count(), 0)

    def test_an_edit_request_with_nothing_proposed_is_refused(self):
        """An empty payload replayed on approval would blank the record."""
        self.grant(self.viewer, self.TAB)
        resp = self.client.post(CREATE, {
            "module": self.MODULE, "object_id": self.record.id, "action": "edit",
        }, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ChangeRequest.objects.count(), 0)

    def test_an_unknown_module_is_refused(self):
        self.grant(self.viewer, self.TAB)
        resp = self.client.post(CREATE, {
            "module": "not_a_module", "object_id": self.record.id,
            "action": "edit", "payload": self.payload(),
        }, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_a_request_against_a_record_that_is_gone_is_refused(self):
        self.grant(self.viewer, self.TAB)
        resp = self.client.post(CREATE, {
            "module": self.MODULE, "object_id": 999999,
            "action": "edit", "payload": self.payload(),
        }, format="json")
        self.assertEqual(resp.status_code, 404)

    def test_the_request_is_labelled_with_the_records_own_number(self):
        """The reviewer sees a queue of numbers, not of row ids."""
        self.grant(self.viewer, self.TAB)
        self.request_edit()
        self.assertEqual(ChangeRequest.objects.get().object_label, self.record.capture_no)

    def test_a_deletion_request_needs_no_payload(self):
        """The other fallback, which the phone has always offered — pinned
        here so the payload rule above is not applied to both."""
        self.grant(self.viewer, self.TAB)
        resp = self.client.post(CREATE, {
            "module": self.MODULE, "object_id": self.record.id, "action": "delete",
        }, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertIsNone(ChangeRequest.objects.get().payload)


class EditRequestRoundTripTests(MobileChangeRequestAPITestCase):
    """What the phone proposes is what an approval writes."""

    def approve_as_reviewer(self, **rights):
        reviewer = get_user_model().objects.create_user(
            username="manager", password="x", email="m@example.com")
        self.grant(reviewer, self.TAB, **rights)
        cr = ChangeRequest.objects.get()
        self.client.force_authenticate(reviewer)
        return self.client.post(
            f"/api/v1/hatchery/change-requests/{cr.id}/approve", {}, format="json")

    def test_the_proposed_values_are_stored_verbatim(self):
        """The payload is replayed by the module's own save, so it has to
        arrive in that save's shape and not the phone's."""
        self.grant(self.viewer, self.TAB)
        self.request_edit(district="Faizabad")
        self.assertEqual(ChangeRequest.objects.get().payload["district"], "Faizabad")

    def test_approving_writes_the_proposal_onto_the_record(self):
        self.grant(self.viewer, self.TAB)
        self.request_edit(district="Faizabad")
        resp = self.approve_as_reviewer(can_edit=True)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.record.refresh_from_db()
        self.assertEqual(self.record.district, "Faizabad")
        self.assertEqual(ChangeRequest.objects.get().status, "approved")

    def test_a_reviewer_without_the_edit_right_cannot_approve(self):
        """Otherwise two people who may not edit could between them make an
        edit, which is the one thing the queue exists to prevent."""
        self.grant(self.viewer, self.TAB)
        self.request_edit(district="Faizabad")
        self.assertEqual(self.approve_as_reviewer(can_edit=False).status_code, 403)
        self.record.refresh_from_db()
        self.assertEqual(self.record.district, "Ambedkar Nagar")
