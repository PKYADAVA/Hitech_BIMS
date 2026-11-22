"""The Send WhatsApp button on a document's own page (Bird Sale first):
the one-document lookup, and sending through the shared endpoint."""

import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from notification.comm_sources import document_row
from notification.models import WhatsappMessage, WhatsappTemplate
from notification.tests import test_doc_sources as _sources


class DocumentButtonTests(TestCase):
    def setUp(self):
        # The same farm, customer and sale the source tests build.
        _sources.SourceRowTests.setUp(self)
        self.user = get_user_model().objects.create_superuser("boss", password="pw12345!")
        self.client.force_login(self.user)
        self.template = WhatsappTemplate.objects.create(
            key="broiler.bird_sale", module="broiler", transaction="broiler_sale",
            name="Bird Sale", template_name="bird_sale_msg", language="en",
            parameter_map=["CustomerName", "Amount"], is_active=True)

    _till = _sources.SourceRowTests._till

    # ---- the one-document lookup -------------------------------------------

    def test_one_sale_comes_back_alone_by_id(self):
        from broiler.models import BirdSale

        other = BirdSale.objects.create(
            farm=self.farm, batch=self.batch, date=self.today, sale_type="customer",
            customer=self.customer, birds=10, net_weight=Decimal("20"),
            rate=Decimal("90"), amount=Decimal("1800"))
        row = document_row("bird_sale", self.sale.id)
        self.assertEqual(row["doc_id"], self.sale.id)
        self.assertNotEqual(row["doc_id"], other.id)

    def test_a_farmer_lifting_has_no_document_to_message_about(self):
        from broiler.models import BirdSale

        lifting = BirdSale.objects.create(
            farm=self.farm, batch=self.batch, date=self.today, sale_type="farmer",
            farmer=self.farmer, birds=50, net_weight=Decimal("100"),
            rate=Decimal("90"), amount=Decimal("9000"))
        self.assertIsNone(document_row("bird_sale", lifting.id))

    def test_lookup_names_the_party_the_template_and_its_filled_values(self):
        r = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "bird_sale", "doc_id": self.sale.id})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d["document"]["party_name"], "Sadar Traders")
        self.assertEqual(d["mobile"], "9876500001")
        self.assertTrue(d["mobile_ok"])
        self.assertEqual([t["id"] for t in d["templates"]], [self.template.id])
        self.assertEqual(d["templates"][0]["params"][0],
                         {"name": "CustomerName", "value": "Sadar Traders"})
        self.assertEqual(d["history"], [])

    def test_only_templates_that_fit_the_document_are_offered(self):
        WhatsappTemplate.objects.create(
            key="broiler.bird_receipt", module="broiler", transaction="bird_receipt",
            name="Receipt", template_name="receipt_msg", is_active=True)
        WhatsappTemplate.objects.create(
            key="broiler.off", module="broiler", transaction="broiler_sale",
            name="Switched off", template_name="off_msg", is_active=False)
        r = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "bird_sale", "doc_id": self.sale.id})
        self.assertEqual([t["name"] for t in r.json()["templates"]], ["Bird Sale"])

    def test_a_module_that_has_not_opted_in_is_refused(self):
        r = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "sales_invoice", "doc_id": 1})
        self.assertEqual(r.status_code, 400)

    def test_an_unknown_document_is_not_found(self):
        r = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "bird_sale", "doc_id": 999999})
        self.assertEqual(r.status_code, 404)

    # ---- sending through the shared endpoint --------------------------------

    def _send(self, **extra):
        fake = mock.Mock()
        fake.send_template.return_value = mock.Mock(
            success=True, status="sent", message_id="wamid.T", provider_message_id="p",
            provider_response={}, error="")
        body = {"module": "bird_sale", "doc_id": self.sale.id,
                "template_id": self.template.id, **extra}
        with mock.patch("notification.services.whatsapp_service.get_whatsapp_service",
                        return_value=fake):
            r = self.client.post(reverse("whatsapp_transaction_send"), json.dumps(body),
                                 content_type="application/json")
        return r, fake

    def test_sending_logs_the_message_against_the_sale(self):
        r, fake = self._send()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(fake.send_template.call_args[0][:2],
                         ("broiler.bird_sale", "9876500001"))
        log = WhatsappMessage.objects.get()
        self.assertEqual((log.module, log.document_no, log.status),
                         ("bird_sale", self.sale.sale_no or self.sale.doc_no, "sent"))

    def test_sent_shows_up_in_the_documents_history(self):
        self._send()
        d = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "bird_sale", "doc_id": self.sale.id}).json()
        self.assertEqual(len(d["history"]), 1)
        self.assertEqual(d["history"][0]["status"], "sent")

    def test_sending_twice_at_once_asks_first(self):
        self._send()
        r, _ = self._send()
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["duplicate"])
        r, _ = self._send(force=True)
        self.assertEqual(r.status_code, 200)

    def test_a_customer_with_no_mobile_cannot_be_sent_to(self):
        self.customer.mobile = ""
        self.customer.mobile_2 = ""
        self.customer.save()
        r, fake = self._send()
        self.assertEqual(r.status_code, 400)
        fake.send_template.assert_not_called()


class BatchLookupTests(TestCase):
    """Several sales at once, for sending a batch from the register."""

    def setUp(self):
        DocumentButtonTests.setUp(self)

    _till = DocumentButtonTests._till

    def _second_sale(self):
        from broiler.models import BirdSale

        return BirdSale.objects.create(
            farm=self.farm, batch=self.batch, date=self.today, sale_type="customer",
            customer=self.customer, birds=10, net_weight=Decimal("20"),
            rate=Decimal("90"), amount=Decimal("1800"))

    def _get(self, ids):
        return self.client.get(reverse("whatsapp_transaction_documents"),
                               {"module": "bird_sale", "doc_ids": ",".join(map(str, ids))})

    def test_each_picked_sale_comes_back_with_its_customer_and_number(self):
        second = self._second_sale()
        d = self._get([self.sale.id, second.id]).json()
        self.assertEqual({x["doc_id"] for x in d["documents"]}, {self.sale.id, second.id})
        self.assertTrue(all(x["mobile_ok"] and x["party_name"] == "Sadar Traders"
                            for x in d["documents"]))
        self.assertEqual(d["skipped"], 0)
        self.assertEqual([t["id"] for t in d["templates"]], [self.template.id])

    def test_a_farmer_lifting_among_the_picks_is_left_out_and_counted(self):
        from broiler.models import BirdSale

        lifting = BirdSale.objects.create(
            farm=self.farm, batch=self.batch, date=self.today, sale_type="farmer",
            farmer=self.farmer, birds=5, net_weight=Decimal("10"),
            rate=Decimal("90"), amount=Decimal("900"))
        d = self._get([self.sale.id, lifting.id]).json()
        self.assertEqual([x["doc_id"] for x in d["documents"]], [self.sale.id])
        self.assertEqual(d["skipped"], 1)

    def test_what_was_already_sent_is_reported_per_sale(self):
        WhatsappMessage.objects.create(
            party_type="customer", party_id=self.customer.id, party_name="Sadar Traders",
            mobile="9876500001", module="bird_sale",
            document_no=self.sale.sale_no or self.sale.doc_no, template=self.template,
            template_name="bird_sale_msg", status="sent")
        d = self._get([self.sale.id]).json()
        self.assertEqual(d["documents"][0]["sent"][0]["template_name"], "bird_sale_msg")

    def test_a_blank_or_oversized_list_is_refused(self):
        self.assertEqual(self._get([]).status_code, 400)
        self.assertEqual(self._get(list(range(1, 202))).status_code, 400)
        r = self.client.get(reverse("whatsapp_transaction_documents"),
                            {"module": "bird_sale", "doc_ids": "1,x"})
        self.assertEqual(r.status_code, 400)


class RegisterStatusTests(TestCase):
    """The sent status and count shown on each Bird Sale row."""

    def setUp(self):
        _sources.SourceRowTests.setUp(self)
        self.user = get_user_model().objects.create_superuser("boss2", password="pw12345!")
        self.client.force_login(self.user)

    _till = _sources.SourceRowTests._till

    def _log(self, status):
        WhatsappMessage.objects.create(
            party_type="customer", party_id=self.customer.id, party_name="Sadar Traders",
            mobile="9876500001", module="bird_sale",
            document_no=self.sale.sale_no or self.sale.doc_no, template_name="t", status=status)

    def _row(self):
        rows = self.client.get(reverse("bird_sale_api_list")).json()
        return next(r for r in rows if r["id"] == self.sale.id)

    def test_a_sale_nobody_was_messaged_about_has_no_status(self):
        self.assertIsNone(self._row()["wa"])

    def test_sent_and_failed_are_counted_separately(self):
        for s in ("sent", "failed", "failed", "delivered"):
            self._log(s)
        wa = self._row()["wa"]
        self.assertEqual((wa["sent"], wa["failed"]), (2, 2))
        # The latest message that got through is the one whose state is shown.
        self.assertEqual(wa["status"], "delivered")

    def test_only_failures_leave_the_sent_time_empty(self):
        self._log("failed")
        row = self._row()
        self.assertEqual(row["wa"]["sent"], 0)
        self.assertIsNone(row["wa_sent_at"])


class MessagePreviewTests(TestCase):
    """The template's wording, carried so the dialogs can show the finished message."""

    def setUp(self):
        _sources.SourceRowTests.setUp(self)
        self.user = get_user_model().objects.create_superuser("boss3", password="pw12345!")
        self.client.force_login(self.user)
        self.template = WhatsappTemplate.objects.create(
            key="broiler.bird_sale", module="broiler", transaction="broiler_sale",
            name="Bird Sale", template_name="bird_sale_msg", language="en",
            parameter_map=["CustomerName", "Amount"], is_active=True,
            body_preview="Hello {{1}}, your total is Rs {{2}}.")

    _till = _sources.SourceRowTests._till

    def test_the_single_lookup_carries_the_wording(self):
        d = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "bird_sale", "doc_id": self.sale.id}).json()
        self.assertEqual(d["templates"][0]["body_preview"], "Hello {{1}}, your total is Rs {{2}}.")

    def test_the_batch_lookup_carries_each_documents_values_for_the_templates_fields(self):
        d = self.client.get(reverse("whatsapp_transaction_documents"),
                            {"module": "bird_sale", "doc_ids": str(self.sale.id)}).json()
        self.assertEqual(d["templates"][0]["parameter_map"], ["CustomerName", "Amount"])
        self.assertEqual(d["documents"][0]["vars"],
                         {"CustomerName": "Sadar Traders", "Amount": "76,000.00"})

    def test_the_wording_can_be_saved_and_read_back_on_a_template(self):
        import json as _json

        r = self.client.put(
            reverse("whatsapp_template_edit", args=[self.template.id]),
            _json.dumps({"module": "broiler", "transaction": "broiler_sale", "name": "Bird Sale",
                         "template_name": "bird_sale_msg", "language": "en",
                         "parameter_map": ["CustomerName"], "body_preview": "  Hi {{1}}  "}),
            content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.template.refresh_from_db()
        self.assertEqual(self.template.body_preview, "Hi {{1}}")

    def test_a_template_without_wording_still_works(self):
        self.template.body_preview = ""
        self.template.save()
        d = self.client.get(reverse("whatsapp_transaction_document"),
                            {"module": "bird_sale", "doc_id": self.sale.id}).json()
        self.assertEqual(d["templates"][0]["body_preview"], "")
