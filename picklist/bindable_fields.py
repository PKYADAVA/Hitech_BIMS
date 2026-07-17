# picklist/bindable_fields.py
"""
Curated allowlist of model fields that can be bound to a picklist.

A developer adds an entry here when building a new form and deciding a field
should be admin-configurable (free text vs a managed list). This intentionally
stops an admin from typing an arbitrary/typo'd field name into a Field
Binding — only fields listed here are selectable in that screen.

Entry shape: (app_label, model_name, field_name, human_label)
"""

BINDABLE_FIELDS = [
    ("purchase", "Supplier", "state", "Supplier - State of Supply"),
    ("purchase", "Supplier", "contact_type", "Supplier - Party Type"),
    ("purchase", "Supplier", "party_category", "Supplier - Party Category"),
    ("purchase", "Supplier", "supplier_group", "Supplier - Supplier Group"),
    ("sales", "Customer", "state", "Customer - State of Supply"),
    ("sales", "Customer", "contact_type", "Customer - Party Type"),
    ("sales", "Customer", "party_category", "Customer - Party Category"),
]

# (app_label, model_name, field_name) -> human_label
BINDABLE_FIELD_LOOKUP = {
    (app_label, model_name, field_name): human_label
    for app_label, model_name, field_name, human_label in BINDABLE_FIELDS
}
