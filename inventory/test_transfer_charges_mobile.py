"""Transfer Charges on the phone.

The endpoints delegate to the web module's own views, so these tests are
about the delegation: that the phone reaches the same rows, the same
masters, the same posting and the same trip lookup, that a refusal comes
back as a refusal, and that the matrix still governs who may do it. Reuses
the service-layer fixture (``TransferChargePostingTests``) exactly as
``test_petty_mobile.py`` reuses ``PettyExpenseTestCase``.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from rest_framework.test import APITestCase

from inventory.models import TransferChargeHeader, TransferChargeLine
from inventory.test_transfer_charges import TransferChargePostingTests


class TransferChargeMobileTests(TransferChargePostingTests, APITestCase):
    ROWS = "/api/v1/inventory/transfer-charges/rows"
    MASTERS = "/api/v1/inventory/transfer-charges/masters"
    SAVE = "/api/v1/inventory/transfer-charges/save"
    LOOKUP = "/api/v1/inventory/transfer-charges/stock-transfer-lookup"
    ALLOCATE_PREVIEW = "/api/v1/inventory/transfer-charges/allocate-preview"

    def setUp(self):
        self.client.force_authenticate(self.user)

    def body(self, **over):
        payload = {
            "dc_no": "DC-TEST-1", "charge_date": self.t1.date.isoformat(),
            "stock_transfer_ids": [self.t1.id, self.t2.id],
            "paid_from": self.cash.id,
            "lines": [{
                "charge_type": self.transport.id, "description": "Vehicle Freight",
                "charge_scope": "Common", "basis": "Fixed", "total_amount": "1000",
                "allocation_method": "By Quantity",
            }],
        }
        payload.update(over)
        return payload

    # -- the register -----------------------------------------------------

    def test_the_list_carries_the_same_rows_as_the_web(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        response = self.client.get(self.ROWS)
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["data"]
        ids = [r["id"] for r in rows]
        self.assertIn(header.id, ids)

    def test_the_phone_filters_are_the_registers_filters(self):
        header = self.make_header()
        response = self.client.get(self.ROWS, {"farm": self.farm1.id})
        ids = [r["id"] for r in response.json()["data"]]
        self.assertIn(header.id, ids)

    # -- the entry screen -------------------------------------------------

    def test_the_pickers_are_filled_from_one_call(self):
        masters = self.client.get(self.MASTERS).json()["data"]
        for key in ("charge_types", "branches", "farms", "statuses", "treatments",
                   "payment_modes", "allocation_methods", "scopes",
                   "bank_cash_accounts", "payable_accounts"):
            self.assertIn(key, masters, key)
        self.assertTrue(masters["charge_types"])

    def test_the_trip_lookup_groups_by_dc_no_and_date(self):
        response = self.client.get(self.LOOKUP, {"q": "DC-TEST-1"})
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["data"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["farm_count"], 2)
        self.assertEqual(set(rows[0]["stock_transfer_ids"]), {self.t1.id, self.t2.id})

    def test_the_allocation_preview_matches_the_service_math(self):
        body = {
            "farms": [
                {"farm_id": self.farm1.id, "quantity": "150", "stock_value": "6300"},
                {"farm_id": self.farm2.id, "quantity": "80", "stock_value": "3360"},
            ],
            "total_amount": "1000", "allocation_method": "By Quantity",
        }
        response = self.client.post(self.ALLOCATE_PREVIEW, body, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        rows = response.json()["data"]["rows"]
        self.assertEqual(sum(Decimal(str(r["allocated_amount"])) for r in rows), Decimal("1000"))

    # -- saving / posting / cancelling -------------------------------------

    def test_saving_a_draft_from_the_phone_is_a_draft_on_the_web(self):
        response = self.client.post(self.SAVE, self.body(), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        header = TransferChargeHeader.objects.get(pk=data["id"])
        self.assertEqual(header.status, TransferChargeHeader.STATUS_DRAFT)
        self.assertEqual(header.dc_no, "DC-TEST-1")

    def test_saving_and_posting_from_the_phone_in_one_call(self):
        response = self.client.post(self.SAVE, self.body(action="post"), format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()["data"]
        self.assertEqual(data["status"], TransferChargeHeader.STATUS_POSTED)

    def test_a_refusal_reads_as_a_refusal(self):
        """A line with no Charge Type chosen is refused at save time -- and
        the phone is told why rather than being handed a 500."""
        response = self.client.post(
            self.SAVE, self.body(lines=[{"charge_type": "", "total_amount": "100"}]), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Charge Type", str(response.json()))

    def test_a_charge_opens_again_in_full(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        data = self.client.get(f"/api/v1/inventory/transfer-charges/{header.pk}").json()["data"]
        self.assertEqual(data["id"], header.pk)
        self.assertEqual(len(data["lines"]), 1)

    def test_posting_from_the_row_menu(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        response = self.client.post(f"/api/v1/inventory/transfer-charges/{header.pk}/post")
        self.assertEqual(response.status_code, 200, response.content)
        header.refresh_from_db()
        self.assertEqual(header.status, TransferChargeHeader.STATUS_POSTED)

    def test_posting_twice_is_refused_as_a_duplicate(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        self.client.post(f"/api/v1/inventory/transfer-charges/{header.pk}/post")

        second = self.make_header()
        TransferChargeLine.objects.create(
            header=second, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("300"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        response = self.client.post(f"/api/v1/inventory/transfer-charges/{second.pk}/post")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already been posted", str(response.json()))

    def test_cancel_reverses_through_the_journal_engine(self):
        header = self.make_header()
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        self.client.post(f"/api/v1/inventory/transfer-charges/{header.pk}/post")
        response = self.client.post(
            f"/api/v1/inventory/transfer-charges/{header.pk}/cancel", {"reason": "test"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        header.refresh_from_db()
        self.assertEqual(header.status, TransferChargeHeader.STATUS_CANCELLED)

    def test_a_draft_can_be_deleted(self):
        header = self.make_header()
        response = self.client.delete(f"/api/v1/inventory/transfer-charges/{header.pk}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(TransferChargeHeader.objects.filter(pk=header.pk).exists())

    # -- who may --------------------------------------------------------

    def test_the_phone_is_held_to_the_same_matrix(self):
        """Mapped to the register's own tab, so a user the matrix does not
        give it to is refused here exactly as they are in the browser."""
        from user.models import GroupTabPermission

        outsider = get_user_model().objects.create_user(username="outsider", password="x")
        group = Group.objects.create(name="Hatchery only")
        outsider.groups.add(group)
        GroupTabPermission.objects.create(group=group, tab_code="batches", can_view=True)

        self.client.force_authenticate(outsider)
        self.assertEqual(self.client.get(self.ROWS).status_code, 403)
        self.assertEqual(self.client.post(self.SAVE, self.body(), format="json").status_code, 403)

    def test_without_a_login_nothing_is_reachable(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.ROWS).status_code, 401)
