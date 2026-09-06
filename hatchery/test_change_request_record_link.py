"""The Record column links to the page the record lives on.

A reviewer looking at a change request wants to see the record in its own
screen, and the number was plain text — leaving them to work out which module
it belonged to and find it by hand.

The link is resolved from the permission tab each module already registers,
because a tab's code is also the url name of its page. Registering a second
thing per module would have meant twenty-nine registrations kept in step, and
the thirtieth forgetting one.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from hatchery.change_requests import (CHANGE_REQUEST_HANDLERS, _date_field,
                                      _record_url, record_dates)
from hatchery.models import ChangeRequest


class ChangeRequestTestCase(TestCase):
    """A real farm and a real record. The link is only offered for a record
    that still exists, so a request pointing at nothing proves nothing."""

    def setUp(self):
        from broiler.models import (Branch, BroilerFarm, BroilerLine, Farmer,
                                    Region, Supervisor)

        self.admin = get_user_model().objects.create_superuser(
            username="reviewer", password="x", email="r@example.com")
        self.client.force_login(self.admin)

        region = Region.objects.create(code="R1", description="East")
        branch = Branch.objects.create(code="B1", branch_name="Akbarpur", region=region)
        self.supervisor = Supervisor.objects.create(branch=branch, name="S. Kumar")
        self.farm = BroilerFarm.objects.create(
            farm_name="Akbarpur Farm", branch=branch, region=region,
            supervisor=self.supervisor,
            line=BroilerLine.objects.create(description="Line 1", region=region,
                                            branch=branch),
            farmer=Farmer.objects.create(farmer_name="Abhishek Kumar Singh"),
            farm_capacity=5000)

    def rows(self):
        return self.client.get(reverse("change_request_api_list")).json()["requests"]

    def bird_sale(self, on=None):
        from datetime import date

        from broiler.models import BirdSale

        return BirdSale.objects.create(farm=self.farm, sale_type="customer",
                                       date=on or date(2026, 7, 15))

    def daily_entry(self, on=None):
        from datetime import date

        from broiler.models import DailyEntry

        return DailyEntry.objects.create(farm=self.farm, supervisor=self.supervisor,
                                         date=on or date(2026, 7, 15))

    def request_for(self, module, label="TR-0001", object_id=1):
        return ChangeRequest.objects.create(
            module=module, object_id=object_id, object_label=label,
            action="edit", payload={"x": 1}, requested_by=self.admin)


class RecordLinkTests(ChangeRequestTestCase):

    def test_every_registered_module_can_name_the_page_its_records_live_on(self):
        """The guard that matters. A module whose tab is not a reversible url
        name would silently lose its link, and nothing else would notice."""
        unresolvable = [key for key, handler in CHANGE_REQUEST_HANDLERS.items()
                        if not _record_url(handler, self.admin)]
        self.assertEqual(unresolvable, [],
                         "these modules have no page to link a record to")

    def test_a_request_carries_the_url_of_its_records_page(self):
        self.request_for("bird_sale", "BS-2627-0008", self.bird_sale().id)
        row = self.rows()[0]
        self.assertEqual(row["record_url"], reverse("bird_sale_list"))
        self.assertEqual(row["object_label"], "BS-2627-0008")

    def test_a_module_that_is_not_registered_gets_no_link(self):
        """An old request whose module was since removed still has to render,
        as plain text rather than an error."""
        self.request_for("a_module_that_no_longer_exists")
        self.assertEqual(self.rows()[0]["record_url"], "")

    def test_the_link_is_withheld_from_someone_who_cannot_open_that_page(self):
        """Offering a link that can only end in a permission error is worse
        than showing none. They can still read the record through the
        proposed-changes view.

        The user needs a matrix of their own for this: someone with no
        configuration at all is unrestricted by design, which is what keeps
        pre-existing accounts working.
        """
        from user.models import UserProfile, UserTabPermission

        self.request_for("bird_sale", object_id=self.bird_sale().id)
        restricted = get_user_model().objects.create_user(
            username="restricted", password="x", email="x@example.com")
        UserProfile.objects.update_or_create(
            user=restricted, defaults={"individual_permissions": True})
        # Granted one unrelated tab, so the matrix counts as configured and
        # everything else is refused.
        # Change Requests itself, or they could not reach this page at all,
        # and Daily Entry as the unrelated tab. Bird Sale is not granted.
        for tab in ("change_requests", "daily_entry_list"):
            UserTabPermission.objects.create(user=restricted, tab_code=tab,
                                             can_view=True)

        self.client.force_login(restricted)
        self.assertEqual(self.rows()[0]["record_url"], "")

    def test_the_link_is_offered_on_a_page_that_user_can_open(self):
        """The other half of the same rule — withholding everything would be
        just as wrong as offering everything."""
        from user.models import UserProfile, UserTabPermission

        self.request_for("daily_entry", "DE-0001", self.daily_entry().id)
        allowed = get_user_model().objects.create_user(
            username="allowed", password="x", email="a@example.com")
        UserProfile.objects.update_or_create(
            user=allowed, defaults={"individual_permissions": True})
        for tab in ("change_requests", "daily_entry_list"):
            UserTabPermission.objects.create(user=allowed, tab_code=tab,
                                             can_view=True)

        self.client.force_login(allowed)
        self.assertEqual(self.rows()[0]["record_url"], reverse("daily_entry_list"))

    def test_the_page_still_lists_the_record_when_there_is_no_link(self):
        """The number is the point of the column; the link is a convenience."""
        self.request_for("a_module_that_no_longer_exists", "TR-0009")
        row = self.rows()[0]
        self.assertEqual(row["object_label"], "TR-0009")
        self.assertEqual(row["record_url"], "")

class RecordDateTests(ChangeRequestTestCase):
    """The register a link lands on opens on today or the last week, so a link
    to an older record has to bring its date with it or arrive at an empty
    list — which reads as the record having been deleted."""

    def test_every_module_has_a_date_to_filter_its_register_by(self):
        missing = [key for key, h in CHANGE_REQUEST_HANDLERS.items()
                   if h.get("model") and not _date_field(h["model"])]
        self.assertEqual(missing, [], "these modules cannot date their own records")

    def test_a_created_stamp_is_not_mistaken_for_the_transaction_date(self):
        """auto_now_add is when the row was typed, not when the sale happened,
        and a register filters on the latter."""
        from broiler.models import BirdSale

        self.assertEqual(_date_field(BirdSale), "date")

    def test_the_request_carries_the_records_own_date(self):
        from datetime import date

        from broiler.models import BirdSale

        sale = self.bird_sale(date(2026, 7, 15))
        ChangeRequest.objects.create(module="bird_sale", object_id=sale.id,
                                     object_label="BS-0001", action="edit",
                                     payload={"x": 1}, requested_by=self.admin)
        row = self.rows()[0]
        self.assertEqual(row["record_date"], "2026-07-15")
        self.assertEqual(row["record_url"], reverse("bird_sale_list"))

    def test_a_record_that_no_longer_exists_offers_no_link(self):
        """An approved deletion leaves the request on this page with nothing
        for it to point at. A link to a register that cannot contain it reads
        as the register being broken."""
        ChangeRequest.objects.create(module="bird_sale", object_id=999999,
                                     object_label="BS-GONE", action="delete",
                                     requested_by=self.admin)
        row = self.rows()[0]
        self.assertEqual(row["record_url"], "")
        self.assertEqual(row["record_date"], "")
        self.assertEqual(row["object_label"], "BS-GONE")

    def test_dates_are_looked_up_once_per_module_not_once_per_row(self):
        """The register loads three hundred requests at a time."""
        from datetime import date

        from broiler.models import BirdSale

        requests = []
        for n in range(5):
            sale = self.bird_sale(date(2026, 7, 15))
            requests.append(ChangeRequest.objects.create(
                module="bird_sale", object_id=sale.id, object_label=f"BS-{n}",
                action="edit", payload={"x": 1}, requested_by=self.admin))
        with self.assertNumQueries(1):
            dates = record_dates(requests)
        self.assertEqual(len(dates), 5)
