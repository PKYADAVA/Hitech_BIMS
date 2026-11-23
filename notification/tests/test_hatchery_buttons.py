"""The Send WhatsApp button on the Chick Sale, Delivery Challan and Chick Receipt registers:
the one- and several-document lookups, sending through the shared endpoint,
the sent status on each register row, and the button showing on the page."""

import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from notification.comm_sources import document_row
from notification.models import WhatsappMessage, WhatsappTemplate
from notification.tests import test_doc_sources as _sources


class HatcheryButtonTests(TestCase):
    def setUp(self):
        from hatchery.models import ChickSale, DeliveryChallan
        from inventory.models import Warehouse
        from sales.models import Customer

        self.today = timezone.localdate()
        self.customer = Customer.objects.create(
            name="Sadar Traders", mobile="9876500001", phone="0522-100001")
        self.warehouse = Warehouse.objects.create(name="Hatchery Counter")
        self.challan = DeliveryChallan.objects.create(
            date=self.today, customer=self.customer, warehouse=self.warehouse,
            vehicle_no="UP53TT6785", driver_name="Ram")
        self.sale = ChickSale.objects.create(
            date=self.today, customer=self.customer, warehouse=self.warehouse,
            vehicle="UP53TT6785", driver="Ram", final_amount=Decimal("12500.00"))
        from hatchery.models import ChickSaleReceipt

        self.receipt = ChickSaleReceipt.objects.create(
            date=self.today, customer=self.customer, location=self.warehouse,
            mode="Bank Transfer", amount=Decimal("5000.00"), receipt_account=self._till())
        self.user = get_user_model().objects.create_superuser("boss", password="pw12345!")
        self.client.force_login(self.user)
        self.receipt_tpl = WhatsappTemplate.objects.create(
            key="hatchery.chick_receipt", module="hatchery", transaction="chick_receipt",
            name="Chick Receipt", template_name="chick_receipt_msg", language="en",
            parameter_map=["CustomerName", "PaidAmount", "ReceiptNo"], is_active=True)
        self.sale_tpl =WhatsappTemplate.objects.create(
            key="hatchery.chick_sale", module="hatchery", transaction="chick_sale",
            name="Chick Sale", template_name="chick_sale_msg", language="en",
            parameter_map=["CustomerName", "Amount"], is_active=True)
        self.dc_tpl = WhatsappTemplate.objects.create(
            key="hatchery.delivery_challan", module="hatchery", transaction="delivery_challan",
            name="Delivery Challan", template_name="challan_msg", language="en",
            parameter_map=["CustomerName", "VehicleNo"], is_active=True)

    _till = _sources.SourceRowTests._till

    # ---- Chick Receipt -----------------------------------------------------

    def test_a_receipt_looks_up_by_id_with_its_own_templates_and_values(self):
        from hatchery.models import ChickSaleReceipt

        other = ChickSaleReceipt.objects.create(
            date=self.today, customer=self.customer, location=self.warehouse,
            amount=Decimal("100"), receipt_account=self.receipt.receipt_account)
        self.assertEqual(document_row("chick_receipt", self.receipt.id)["doc_id"], self.receipt.id)
        d = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "chick_receipt", "doc_id": self.receipt.id}).json()
        self.assertEqual(d["document"]["label"], "Chick Receipt")
        self.assertEqual(d["document"]["doc_no"], self.receipt.receipt_no)
        self.assertNotEqual(d["document"]["doc_id"], other.id)
        self.assertEqual([t["id"] for t in d["templates"]], [self.receipt_tpl.id])
        self.assertEqual([p["value"] for p in d["templates"][0]["params"]],
                         ["Sadar Traders", "5,000.00", self.receipt.receipt_no])
        d = self.client.get(reverse("whatsapp_transaction_documents"), {
            "module": "chick_receipt", "doc_ids": f"{self.receipt.id},{other.id}"}).json()
        self.assertEqual(len(d["documents"]), 2)

    def test_sending_a_receipt_logs_it_and_marks_the_register(self):
        r, _ = self._send("chick_receipt", self.receipt.id, self.receipt_tpl)
        self.assertEqual(r.status_code, 200)
        log = WhatsappMessage.objects.get()
        self.assertEqual((log.module, log.document_no), ("chick_receipt", self.receipt.receipt_no))
        self.assertEqual(self.client.get(reverse("chick_sale_receipt_api_list")).json()[0]["wa"]["sent"], 1)

    def test_the_receipt_register_offers_sending_only_to_someone_who_may_send(self):
        html = self.client.get(reverse("chick_sale_receipt_list")).content.decode()
        self.assertIn('id="cr-multi-toggle"', html)
        with mock.patch("user.access.user_can", return_value=False):
            html = self.client.get(reverse("chick_sale_receipt_list")).content.decode()
        self.assertNotIn('id="cr-multi-toggle"', html)

    # ---- the one-document lookup -------------------------------------------

    def test_a_sale_and_a_challan_each_come_back_alone_by_id(self):
        from hatchery.models import ChickSale, DeliveryChallan

        other_sale = ChickSale.objects.create(
            date=self.today, customer=self.customer, warehouse=self.warehouse)
        other_dc = DeliveryChallan.objects.create(date=self.today, customer=self.customer)
        self.assertEqual(document_row("sales", self.sale.id)["doc_id"], self.sale.id)
        self.assertEqual(document_row("dispatch", self.challan.id)["doc_id"], self.challan.id)
        self.assertNotEqual(document_row("sales", self.sale.id)["doc_id"], other_sale.id)
        self.assertNotEqual(document_row("dispatch", self.challan.id)["doc_id"], other_dc.id)

    def test_the_lookup_offers_only_the_templates_for_that_document(self):
        d = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "sales", "doc_id": self.sale.id}).json()
        self.assertEqual(d["document"]["label"], "Chick Sale")
        self.assertEqual(d["document"]["doc_no"], self.sale.bill_no)
        self.assertEqual([t["id"] for t in d["templates"]], [self.sale_tpl.id])
        self.assertEqual(d["templates"][0]["params"][1], {"name": "Amount", "value": "12,500.00"})
        self.assertTrue(d["mobile_ok"])

        d = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "dispatch", "doc_id": self.challan.id}).json()
        self.assertEqual(d["document"]["label"], "Delivery Challan")
        self.assertEqual(d["document"]["doc_no"], self.challan.challan_no)
        self.assertEqual([t["id"] for t in d["templates"]], [self.dc_tpl.id])
        self.assertEqual(d["templates"][0]["params"][1], {"name": "VehicleNo", "value": "UP53TT6785"})

    def test_several_come_back_together_for_a_batch(self):
        from hatchery.models import ChickSale

        second = ChickSale.objects.create(
            date=self.today, customer=self.customer, warehouse=self.warehouse)
        d = self.client.get(reverse("whatsapp_transaction_documents"), {
            "module": "sales", "doc_ids": f"{self.sale.id},{second.id}"}).json()
        self.assertEqual(sorted(x["doc_no"] for x in d["documents"]),
                         sorted([self.sale.bill_no, second.bill_no]))
        d = self.client.get(reverse("whatsapp_transaction_documents"), {
            "module": "dispatch", "doc_ids": str(self.challan.id)}).json()
        self.assertEqual([x["doc_no"] for x in d["documents"]], [self.challan.challan_no])

    # ---- sending, and the status it leaves on the register ------------------

    def _send(self, module, doc_id, template):
        fake = mock.Mock()
        fake.send_template.return_value = mock.Mock(
            success=True, status="sent", message_id="wamid.T", provider_message_id="p",
            provider_response={}, error="")
        with mock.patch("notification.services.whatsapp_service.get_whatsapp_service",
                        return_value=fake):
            r = self.client.post(reverse("whatsapp_transaction_send"), json.dumps(
                {"module": module, "doc_id": doc_id, "template_id": template.id}),
                content_type="application/json")
        return r, fake

    def test_sending_a_chick_sale_logs_it_against_the_bill_and_marks_the_register(self):
        r, fake = self._send("sales", self.sale.id, self.sale_tpl)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fake.send_template.call_args[0][:2],
                         ("hatchery.chick_sale", "9876500001"))
        log = WhatsappMessage.objects.get()
        self.assertEqual((log.module, log.document_no), ("sales", self.sale.bill_no))
        rows = self.client.get(reverse("chick_sale_api_list")).json()
        self.assertEqual(rows[0]["wa"]["sent"], 1)

    def test_sending_a_challan_logs_it_against_the_challan_and_marks_the_register(self):
        r, _ = self._send("dispatch", self.challan.id, self.dc_tpl)
        self.assertEqual(r.status_code, 200)
        log = WhatsappMessage.objects.get()
        self.assertEqual((log.module, log.document_no), ("dispatch", self.challan.challan_no))
        rows = self.client.get(reverse("delivery_challan_api_list")).json()
        self.assertEqual(rows[0]["wa"]["sent"], 1)

    def test_a_document_nobody_was_messaged_about_has_no_status(self):
        self.assertIsNone(self.client.get(reverse("chick_sale_api_list")).json()[0]["wa"])
        self.assertIsNone(self.client.get(reverse("delivery_challan_api_list")).json()[0]["wa"])

    def test_a_challans_message_does_not_mark_a_sale_with_the_same_number(self):
        # Logged per module: a challan number can never light up a sale's button.
        WhatsappMessage.objects.create(
            party_type="customer", party_id=self.customer.id, party_name="Sadar Traders",
            mobile="9876500001", module="dispatch", document_no=self.sale.bill_no,
            template_name="t", status="sent")
        self.assertIsNone(self.client.get(reverse("chick_sale_api_list")).json()[0]["wa"])

    # ---- the button on the page ---------------------------------------------

    def test_the_registers_offer_sending_to_someone_who_may_send(self):
        html = self.client.get(reverse("chick_sale_list")).content.decode()
        self.assertIn('id="cs-multi-toggle"', html)
        self.assertIn('id="cs-bulk-whatsapp"', html)
        html = self.client.get(reverse("delivery_challan_list")).content.decode()
        self.assertIn('id="dc-multi-toggle"', html)
        self.assertIn('id="dc-bulk-whatsapp"', html)

    def test_the_registers_hide_sending_from_someone_who_may_not(self):
        with mock.patch("user.access.user_can", return_value=False):
            # The page's script names the toggle either way; it is the button
            # element itself that must be missing.
            for name, marker in (("chick_sale_list", 'id="cs-multi-toggle"'),
                                 ("delivery_challan_list", 'id="dc-multi-toggle"')):
                html = self.client.get(reverse(name)).content.decode()
                self.assertNotIn(marker, html)
