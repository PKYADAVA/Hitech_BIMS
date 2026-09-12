"""A receipt takes whatever mode the Payment Mode master offers.

These four forms fill their Mode dropdown from ``active_payment_modes`` — the
master an office user maintains — while the models kept the five names that
predate it. Adding a mode called "Paytm Business Wallet" therefore produced a
dropdown entry that could be chosen and not saved:

    mode: Value 'Paytm Business Wallet' is not a valid choice.

Two things were wrong, and the second would have outlived a fix to the first:
the field pinned a stale list, and at twenty characters it was too short for
the name anyway. The master's own docstring says what these fields are — "the
transaction's own ``mode`` field stays a plain name string" — which is what
they now are.
"""
from __future__ import annotations

from django.test import TestCase

from account.models import PaymentMode
from broiler.models import BirdSaleReceipt, FarmerGCPaymentLine
from hatchery.models import ChickSaleReceipt
from purchase.models import SupplierPaymentLine
from sales.models import SalesReceipt

#: Long enough to have failed the old max_length=20 on its own.
CUSTOM_MODE = "Paytm Business Wallet"

#: Every model whose form is fed from the master. GC Payment joined them: its
#: form built the dropdown from the hardcoded list, so a mode the office added
#: appeared on every other payment form and not on that one.
MASTER_DRIVEN = (BirdSaleReceipt, ChickSaleReceipt, SupplierPaymentLine,
                 SalesReceipt, FarmerGCPaymentLine)


class ReceiptModeTests(TestCase):
    def test_the_mode_field_pins_no_stale_list(self):
        for model in MASTER_DRIVEN:
            with self.subTest(model=model.__name__):
                field = model._meta.get_field("mode")
                self.assertFalse(
                    field.choices,
                    f"{model.__name__}.mode pins its own list, so a mode added to "
                    f"the master can be offered in the dropdown and refused on save")

    def test_the_mode_field_can_hold_a_master_mode_name(self):
        name_max = PaymentMode._meta.get_field("name").max_length
        for model in MASTER_DRIVEN:
            with self.subTest(model=model.__name__):
                self.assertGreaterEqual(
                    model._meta.get_field("mode").max_length, name_max,
                    f"{model.__name__}.mode is shorter than a mode's name can be")

    def test_a_custom_mode_passes_validation(self):
        """The reported failure, as the form performs it."""
        for model in MASTER_DRIVEN:
            with self.subTest(model=model.__name__):
                field = model._meta.get_field("mode")
                field.clean(CUSTOM_MODE, None)      # raises ValidationError if not

    def test_the_named_mode_is_one_the_master_can_hold(self):
        self.assertLessEqual(len(CUSTOM_MODE),
                             PaymentMode._meta.get_field("name").max_length)


class ModeDropdownSourceTests(TestCase):
    """Every form that offers a mode offers the ones an office can define."""

    def test_no_view_hands_a_template_the_hardcoded_list(self):
        import re
        from pathlib import Path

        from django.conf import settings

        offenders = []
        for app in ("broiler", "sales", "purchase", "hatchery"):
            for path in (Path(settings.BASE_DIR) / app).rglob("views*.py"):
                for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    # A route planner's travel mode is a different thing.
                    if re.search(r'"(mode_choices|modes)":\s*\w+\.MODE_CHOICES', line):
                        offenders.append(f"{path.name}:{i}")
        self.assertEqual(offenders, [], chr(10).join([
            "These hand a template the five names that predate the Payment Mode",
            "master, so a mode the office adds cannot be chosen there:", *offenders]))
