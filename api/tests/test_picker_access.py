"""A transaction tab is enough to fill its own pickers — and no more.

The phone's Bird Sale form opened with an empty Customer list and an empty
Lifting Supervisor list for a user who had Bird Sale and not the Customer or
Employee master: both pickers ask a master endpoint, and the gate refused it.
The web page for the same user was never broken, because it is handed its
customers through view context — holding the transaction is what entitles the
read there. These tests hold the API to that same rule.

Two halves, and both matter. The gate opens the read (``PICKER_MASTERS``); the
serializer narrows the row (``PICKER_FIELDS``). Employee is why the second half
exists — the full record carries salary, bank account, IFSC and Aadhaar.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase

from api.serializers import picker_serializer
from hr.models import Employee
from sales.models import Customer
from user.models import GroupTabPermission


class PickerAccessTests(TestCase):
    """A Bird Sale user, with no rights on any master."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.seller = User.objects.create_user("api_seller", "s@x.com",
                                               "Str0ngPass!")
        group = Group.objects.create(name="Bird Sellers")
        self.seller.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="bird_sale_list",
                                          can_view=True, can_add=True)

        Customer.objects.create(code="C1", name="Ramesh Traders")
        # employee_id is assigned by the model itself, and is an integer.
        Employee.objects.create(full_name="Suresh Kumar", salary=45000)
        self.client.force_login(self.seller)

    # ---- the gate --------------------------------------------------------

    def test_the_customer_picker_fills(self):
        response = self.client.get("/api/v1/sales/customers/")
        self.assertEqual(response.status_code, 200)

    def test_the_shared_customer_route_fills_too(self):
        """Both routes serve the same model, so both must behave the same."""
        response = self.client.get("/api/v1/customers/")
        self.assertEqual(response.status_code, 200)

    def test_the_employee_picker_fills(self):
        response = self.client.get("/api/v1/hr/employees/?relieve=false")
        self.assertEqual(response.status_code, 200)

    def test_a_master_no_held_tab_asks_for_is_still_refused(self):
        """Suppliers belong to purchases. This user does not sell to them."""
        response = self.client.get("/api/v1/purchase/suppliers/")
        self.assertEqual(response.status_code, 403)

    def test_writing_the_master_is_still_refused(self):
        """The read is opened. Creating a customer still needs the master."""
        response = self.client.post("/api/v1/sales/customers/",
                                    {"name": "New Co"}, content_type="application/json")
        self.assertEqual(response.status_code, 403)

    # ---- the narrowing ---------------------------------------------------

    def _first_row(self, path):
        body = self.client.get(path).json()
        body = body.get("data", body)
        rows = body.get("results", body) if isinstance(body, dict) else body
        self.assertTrue(rows, f"{path} returned no rows to inspect")
        return rows[0]

    def test_the_employee_picker_cannot_see_payroll(self):
        row = self._first_row("/api/v1/hr/employees/?relieve=false")
        for private in ("salary", "bank_name", "ifsc_code", "aadhar_number",
                        "pan_card", "date_of_birth", "personal_contact"):
            self.assertNotIn(private, row, private)

    def test_the_employee_picker_still_has_what_a_dropdown_needs(self):
        row = self._first_row("/api/v1/hr/employees/?relieve=false")
        self.assertEqual(sorted(row), ["employee_id", "full_name", "id"])

    def test_the_customer_picker_is_identity_only(self):
        row = self._first_row("/api/v1/sales/customers/")
        self.assertEqual(sorted(row), ["code", "id", "name"])


class PickerNarrowingIsOnlyForPickersTests(TestCase):
    """Holding the master itself must still return the whole record."""

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.clerk = User.objects.create_user("api_cust_clerk", "c@x.com",
                                              "Str0ngPass!")
        group = Group.objects.create(name="Customer Clerks")
        self.clerk.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="customer",
                                          can_view=True)
        Customer.objects.create(code="C1", name="Ramesh Traders")
        self.client.force_login(self.clerk)

    def test_the_master_holder_sees_the_full_row(self):
        body = self.client.get("/api/v1/sales/customers/").json()
        body = body.get("data", body)
        rows = body.get("results", body) if isinstance(body, dict) else body
        self.assertGreater(len(rows[0]), 3,
                           "narrowed a user who holds the master outright")


class EveryDeclaredPickerIsReachableTests(TestCase):
    """No picker the app declares may be one a transaction user can't read.

    The Bird Sale bug was invisible until someone opened the form: a picker
    points at a master endpoint, the gate refuses it, and the field renders
    empty with nothing to say why. The app's `optionsPath` declarations are the
    full list of those endpoints, so the check can be exhaustive rather than
    waiting for the next report. Same reasoning as the PHONE_SCREENS /
    RESOURCE_TABS sync test: two copies of one fact, and no build step to
    merge them.
    """

    def test_every_options_path_resolves_to_a_readable_master(self):
        import re
        from pathlib import Path

        from django.conf import settings

        from api.permissions import tab_for_view
        from api.urls import router
        from user.access import MASTER_REFERENCE_TABS, PICKER_MASTERS

        mobile = Path(settings.BASE_DIR) / "mobile" / "src"
        if not mobile.exists():                       # server-only checkout
            self.skipTest("mobile client not present")

        declared = set()
        for source in mobile.rglob("*.ts*"):
            declared.update(re.findall(r'optionsPath:\s*"([^"]+)"',
                                       source.read_text(encoding="utf-8")))

        tabs = {prefix.strip("/"): tab_for_view(viewset)
                for prefix, viewset, _basename in router.registry}

        unreachable = []
        for path in sorted(declared):
            tab = tabs.get(path.split("?")[0].strip("/"))
            if tab is None:
                # Either unrouted or not yet mapped to a tab. An unmapped
                # resource is allowed today, and belongs to the audit the
                # WEB_ACCESS_ENFORCE rollout owns, not to this check.
                continue
            if tab not in MASTER_REFERENCE_TABS and tab not in PICKER_MASTERS:
                unreachable.append(f"{path} (tab {tab})")

        self.assertEqual(unreachable, [], "\n".join([
            "These pickers render blank for a user who holds the transaction "
            "but not the master:", *unreachable,
            "Add the master to PICKER_MASTERS with the transaction tabs that "
            "need it, and give it a PICKER_FIELDS row."]))


class EveryPickerMasterIsNarrowedTests(TestCase):
    """Every master the gate can open must also be narrowed when it opens.

    The two halves are declared in different files, and a resource with a
    bespoke viewset can override ``get_serializer_class`` and quietly lose the
    narrowing. Customer and Employee are covered by the cases above; this walks
    the whole of PICKER_MASTERS so a new entry cannot be added with the gate
    half wired and the serializer half missing.
    """

    def test_each_master_opens_narrowed(self):
        from django.contrib.auth.models import Group

        from api.permissions import tab_for_view
        from api.serializers import PICKER_FIELDS
        from api.urls import router
        from user.access import PICKER_MASTERS

        User = get_user_model()
        routes = {}
        for prefix, viewset, _basename in router.registry:
            tab = tab_for_view(viewset)
            # First route wins; several tabs have two (a shared FK-picker
            # route and the module's own), and both go through this gate.
            routes.setdefault(tab, prefix)

        for master, needed_by in sorted(PICKER_MASTERS.items()):
            with self.subTest(master=master):
                prefix = routes.get(master)
                self.assertIsNotNone(prefix, f"{master} has no route")

                cache.clear()
                holder = User.objects.create_user(
                    f"picker_{master}", f"{master}@x.com", "Str0ngPass!")
                group = Group.objects.create(name=f"Holds {master}")
                holder.groups.add(group)
                GroupTabPermission.objects.create(
                    group=group, tab_code=sorted(needed_by)[0], can_view=True)
                self.client.force_login(holder)

                response = self.client.get(f"/api/v1/{prefix}/")
                self.assertEqual(response.status_code, 200,
                                 f"{master} refused for a holder of its transaction")

                # Asserted on the serializer the view actually chose, not on a
                # row: an empty table would make a row check pass without
                # proving anything, and these tables can legitimately be empty.
                view = response.wsgi_request.resolver_match.func.cls()
                view.request = response.wsgi_request
                view.request.picker_only = True
                view.format_kwarg = None
                model = view.queryset.model
                self.assertEqual(
                    view.get_serializer_class(), picker_serializer(model),
                    f"{master} did not narrow — a bespoke get_serializer_class?")
                self.assertIn(f"{model._meta.app_label}.{model.__name__}",
                              PICKER_FIELDS, f"{master} has no PICKER_FIELDS row")


class PhoneGateStillAppliesToPickersTests(TestCase):
    """A transaction hidden from the phone cannot unlock a master on the phone.

    The picker read is granted *because* the user holds a transaction that asks
    for it. Mobile Access can switch that transaction's whole module off, and
    hiding a module has to close its API too — otherwise the master is readable
    through a screen the user cannot open.
    """

    def setUp(self):
        from user.models import GroupMobileAccess

        cache.clear()
        User = get_user_model()
        self.seller = User.objects.create_user("api_offphone", "o@x.com",
                                               "Str0ngPass!")
        self.group = Group.objects.create(name="Web Only Sellers")
        self.seller.groups.add(self.group)
        GroupTabPermission.objects.create(group=self.group,
                                          tab_code="bird_sale_list", can_view=True)
        # Broiler off, and one module on so the user counts as configured.
        GroupMobileAccess.objects.create(group=self.group, module_key="broiler",
                                         enabled=False, position=0)
        GroupMobileAccess.objects.create(group=self.group, module_key="hatchery",
                                         enabled=True, position=1)
        Customer.objects.create(code="C1", name="Ramesh Traders")
        self.client.force_login(self.seller)

    def test_the_picker_is_refused_when_the_module_is_off(self):
        response = self.client.get("/api/v1/sales/customers/")
        self.assertEqual(response.status_code, 403)


class WebPagesFillTheirOwnPickersTests(TestCase):
    """The same sweep, on the web, for every transaction that names a master.

    The web has never had the API's bug, because its forms are handed their
    parties through view context (``customers_for`` and friends) rather than
    asking the master's own endpoint — data-scoped, but not tab-gated. That is
    a property worth pinning rather than assuming: if any of these pages is
    ever rewritten to fetch a master the way the phone does, it starts
    refusing the user who holds only the transaction, and this fails.
    """

    def test_each_transaction_page_opens_for_a_holder_of_just_that_tab(self):
        from django.contrib.auth.models import Group
        from django.urls import NoReverseMatch, reverse

        from user.access import PICKER_MASTERS

        User = get_user_model()
        transactions = sorted({t for tabs in PICKER_MASTERS.values() for t in tabs})

        checked, refused = [], []
        for tab in transactions:
            try:
                url = reverse(tab)
            except NoReverseMatch:
                continue                      # no page of its own to open
            cache.clear()
            holder = User.objects.create_user(f"web_{tab}"[:150], f"{tab}@x.com",
                                              "Str0ngPass!")
            group = Group.objects.create(name=f"Web holds {tab}")
            holder.groups.add(group)
            GroupTabPermission.objects.create(group=group, tab_code=tab,
                                              can_view=True)
            self.client.force_login(holder)
            status = self.client.get(url).status_code
            checked.append(tab)
            if status == 403:
                refused.append(f"{tab} -> {url} refused its own holder")

        self.assertEqual(refused, [], "\n".join(refused))
        self.assertTrue(checked, "no transaction page was reachable to check")


class EnforcementWouldNotBreakTheApiTests(TestCase):
    """Every gated resource is mapped, or deliberately ungated — no accidents.

    ``WEB_ACCESS_ENFORCE`` currently lets an unmapped resource through and only
    records it. On the day it is turned on, every resource still unmapped
    starts refusing every caller, superusers included, because the refusal
    happens before the matrix is consulted. This is the check that says the API
    half of that switch is safe to throw.
    """

    def test_no_gated_resource_is_left_unmapped_by_accident(self):
        from api.permissions import (MatrixPermission, UNGATED_MODELS,
                                     model_for_view, tab_for_view)
        from api.urls import router

        stragglers = []
        for prefix, viewset, _basename in router.registry:
            gated = any(p is MatrixPermission
                        for p in getattr(viewset, "permission_classes", []))
            if not gated or tab_for_view(viewset) is not None:
                continue
            model = model_for_view(viewset)
            label = (f"{model._meta.app_label}.{model.__name__}"
                     if model is not None else "(no model)")
            if label not in UNGATED_MODELS:
                stragglers.append(f"{prefix} ({label})")

        self.assertEqual(stragglers, [], "\n".join([
            "These refuse everyone the moment WEB_ACCESS_ENFORCE is on:",
            *stragglers,
            "Map the model to its tab in MODEL_TABS, or — if no web page owns "
            "it — name it in UNGATED_MODELS with the reason."]))
