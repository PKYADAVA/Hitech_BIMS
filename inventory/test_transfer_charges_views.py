"""The web screens: register, add form, post/cancel actions, attachments and
the report data endpoint — reusing the same fixture as the service-layer
tests so a view test never has to re-establish what a working Transfer
Charge needs.
"""
import json
from decimal import Decimal

from django.urls import reverse

from inventory.models import ChargeType, TransferChargeHeader
from inventory.test_transfer_charges import TransferChargePostingTests


class TransferChargeViewTests(TransferChargePostingTests):
    def setUp(self):
        self.client.force_login(self.user)

    def test_list_page_loads(self):
        resp = self.client.get(reverse("transfer_charge_list"))
        self.assertEqual(resp.status_code, 200)

    def test_add_page_loads(self):
        resp = self.client.get(reverse("transfer_charge_add"))
        self.assertEqual(resp.status_code, 200)

    def test_report_page_loads(self):
        resp = self.client.get(reverse("transfer_charges_report"))
        self.assertEqual(resp.status_code, 200)

    def test_stock_transfer_lookup_finds_the_dc_group(self):
        resp = self.client.get(reverse("transfer_charge_stock_transfer_lookup"), {"q": "DC-TEST-1"})
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["farm_count"], 2)
        self.assertEqual(set(rows[0]["stock_transfer_ids"]), {self.t1.id, self.t2.id})

    def test_stock_transfer_lookup_detail_by_dc_and_date(self):
        resp = self.client.get(reverse("transfer_charge_stock_transfer_lookup"),
                               {"dc_no": "DC-TEST-1", "date": self.t1.date.isoformat()})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["farm_count"], 2)

    def test_allocate_preview_matches_the_service_math(self):
        body = {
            "farms": [
                {"farm_id": self.farm1.id, "quantity": "150", "stock_value": "6300"},
                {"farm_id": self.farm2.id, "quantity": "80", "stock_value": "3360"},
            ],
            "total_amount": "1000", "allocation_method": "By Quantity",
        }
        resp = self.client.post(reverse("transfer_charge_allocate_preview"),
                                data=json.dumps(body), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()["rows"]
        self.assertEqual(sum(Decimal(str(r["allocated_amount"])) for r in rows), Decimal("1000"))

    def test_create_draft_via_api(self):
        body = {
            "dc_no": "DC-TEST-1", "charge_date": self.t1.date.isoformat(),
            "stock_transfer_ids": [self.t1.id, self.t2.id],
            "paid_from": self.cash.id,
            "lines": [{
                "charge_type": self.transport.id, "description": "Vehicle Freight",
                "charge_scope": "Common", "basis": "Fixed", "total_amount": "1000",
                "allocation_method": "By Quantity",
            }],
        }
        resp = self.client.post(reverse("transfer_charge_api_list"),
                                data=json.dumps(body), content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        self.assertEqual(data["status"], TransferChargeHeader.STATUS_DRAFT)
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(sum(Decimal(str(a["allocated_amount"])) for a in data["lines"][0]["allocations"]),
                         Decimal("1000"))

    def test_create_and_post_via_api_in_one_call(self):
        body = {
            "dc_no": "DC-TEST-1", "charge_date": self.t1.date.isoformat(),
            "stock_transfer_ids": [self.t1.id, self.t2.id],
            "paid_from": self.cash.id, "action": "post",
            "lines": [{
                "charge_type": self.transport.id, "description": "Vehicle Freight",
                "charge_scope": "Common", "basis": "Fixed", "total_amount": "1000",
                "allocation_method": "Equal",
            }],
        }
        resp = self.client.post(reverse("transfer_charge_api_list"),
                                data=json.dumps(body), content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()["status"], TransferChargeHeader.STATUS_POSTED)

    def test_post_action_endpoint_blocks_on_missing_ledger(self):
        header = self.make_header()
        self.client.post(
            reverse("transfer_charge_api_list"), content_type="application/json",
            data=json.dumps({"dc_no": "DC-TEST-1"}))
        from inventory.models import TransferChargeLine
        line = TransferChargeLine.objects.create(
            header=header, charge_type=self.unloading, charge_scope=TransferChargeLine.SCOPE_FARM_WISE)
        from inventory.models import TransferChargeAllocation
        TransferChargeAllocation.objects.create(
            line=line, destination_farm=self.farm1, allocated_amount=Decimal("100"))
        resp = self.client.post(reverse("transfer_charge_post", args=[header.id]))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Accounting mapping is not configured", resp.json()["error"])

    def test_cancel_action_endpoint(self):
        header = self.make_header()
        from inventory.models import TransferChargeLine
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        from inventory.services import transfer_charges as service
        service.post(header, user=self.user)
        resp = self.client.post(reverse("transfer_charge_cancel", args=[header.id]),
                                data=json.dumps({"reason": "test"}), content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], TransferChargeHeader.STATUS_CANCELLED)

    def test_draft_can_be_deleted_but_posted_cannot(self):
        header = self.make_header()
        resp = self.client.delete(reverse("transfer_charge_api", args=[header.id]))
        self.assertEqual(resp.status_code, 200)

        header2 = self.make_header()
        from inventory.models import TransferChargeLine
        TransferChargeLine.objects.create(
            header=header2, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("500"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        from inventory.services import transfer_charges as service
        service.post(header2, user=self.user)
        resp2 = self.client.delete(reverse("transfer_charge_api", args=[header2.id]))
        self.assertEqual(resp2.status_code, 400)

    def test_report_data_endpoint_returns_balanced_kpis(self):
        header = self.make_header()
        from inventory.models import TransferChargeLine
        TransferChargeLine.objects.create(
            header=header, charge_type=self.transport, charge_scope=TransferChargeLine.SCOPE_COMMON,
            total_amount=Decimal("1000"), allocation_method=TransferChargeLine.METHOD_EQUAL)
        from inventory.services import transfer_charges as service
        service.post(header, user=self.user)
        resp = self.client.get(reverse("transfer_charges_report_data"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(Decimal(str(data["kpis"]["total_charges"])), Decimal("1000"))
        self.assertEqual(Decimal(str(data["kpis"]["transport"])), Decimal("1000"))

    def test_list_filters_by_farm(self):
        header = self.make_header()
        resp = self.client.get(reverse("transfer_charge_api_list"), {"farm": self.farm1.id})
        self.assertEqual(resp.status_code, 200)
        ids = [r["id"] for r in resp.json()]
        self.assertIn(header.id, ids)
