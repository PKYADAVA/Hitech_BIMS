"""
Seeds the 3 pilot Picklists + Field Bindings: Indian States, Party Type,
Party Category (all STATIC), and Supplier Group (MODEL, sourced from
VendorGroup). Idempotent — safe to run repeatedly (get_or_create throughout).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from hatchery_master.models import STATES_AND_TERRITORIES
from picklist.models import FieldPicklistBinding, Picklist, PicklistValue
from sales.models import Customer


class Command(BaseCommand):
    help = "Seed the pilot Picklists and Field Bindings (states, party type/category, supplier group)."

    @transaction.atomic
    def handle(self, *args, **options):
        state_pl = self._seed_static("indian_state", "Indian States & UTs",
                                      [(s, s) for s in STATES_AND_TERRITORIES])
        party_type_pl = self._seed_static("party_type", "Party Type", Customer.ContactType.choices)
        party_category_pl = self._seed_static("party_category", "Party Category", Customer.PartyCategory.choices)
        vendor_group_pl, _ = Picklist.objects.get_or_create(
            key="vendor_group",
            defaults={"name": "Vendor Group", "source_type": Picklist.SourceType.MODEL,
                      "source_model_key": "vendor_group"},
        )

        bindings = [
            ("purchase", "Supplier", "state", state_pl),
            ("sales", "Customer", "state", state_pl),
            ("purchase", "Supplier", "contact_type", party_type_pl),
            ("sales", "Customer", "contact_type", party_type_pl),
            ("purchase", "Supplier", "party_category", party_category_pl),
            ("sales", "Customer", "party_category", party_category_pl),
            ("purchase", "Supplier", "supplier_group", vendor_group_pl),
        ]
        for app_label, model_name, field_name, picklist in bindings:
            FieldPicklistBinding.objects.get_or_create(
                app_label=app_label, model_name=model_name, field_name=field_name,
                defaults={"mode": FieldPicklistBinding.Mode.PICKLIST, "picklist": picklist},
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded 4 picklists and {len(bindings)} field bindings."
        ))

    def _seed_static(self, key, name, value_label_pairs):
        picklist, _ = Picklist.objects.get_or_create(
            key=key, defaults={"name": name, "source_type": Picklist.SourceType.STATIC},
        )
        for order, (value, label) in enumerate(value_label_pairs):
            PicklistValue.objects.get_or_create(
                picklist=picklist, value=value, defaults={"label": label, "sort_order": order},
            )
        return picklist
