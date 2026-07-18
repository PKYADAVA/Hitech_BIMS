# picklist/bindable_fields.py
"""
Curated allowlist of model fields that can be bound to a picklist.

A developer adds an entry here when building or touching a form and deciding
a field should be admin-configurable (free text vs a managed list). This
intentionally stops an admin from typing an arbitrary/typo'd field name into
a Field Binding — only fields listed here are selectable in that screen.
`picklist.checks` verifies every entry resolves to a real model field on
`python manage.py check`, so a typo or renamed field fails loudly here rather
than silently at render time.

NEVER add a field that is:
  - computed/derived by a formula or aggregation (totals, subtotals, tax
    amounts, net/grand totals, gross/final amounts — anything written by
    business-rule code rather than typed directly by a user)
  - a quantity, rate, weight, or percentage that feeds such a formula
  - a ForeignKey, DateField/DateTimeField, or JSONField
  - free-form narrative/remarks text
  - a single-use identifier (invoice no, vehicle no, DC no, person name)
    rather than a short, repeating category

Picklist Master is for short, repeating category/type/status-like text
columns only — on master screens *and* transaction screens alike.

Entry shape: {app_label, model_name, field_name, label, module, category}
  module   — nav-facing grouping, matches the labels used in
             user/access.py MODULE_REGISTRY (kept consistent, not imported,
             to avoid coupling this app to the access-control app).
  category — "Master" or "Transaction".
"""

BINDABLE_FIELDS = [
    # --- Purchase / Master ---
    {"app_label": "purchase", "model_name": "Supplier", "field_name": "state",
     "label": "Supplier - State of Supply", "module": "Purchase", "category": "Master"},
    {"app_label": "purchase", "model_name": "Supplier", "field_name": "contact_type",
     "label": "Supplier - Party Type", "module": "Purchase", "category": "Master"},
    {"app_label": "purchase", "model_name": "Supplier", "field_name": "party_category",
     "label": "Supplier - Party Category", "module": "Purchase", "category": "Master"},
    {"app_label": "purchase", "model_name": "Supplier", "field_name": "supplier_group",
     "label": "Supplier - Supplier Group", "module": "Purchase", "category": "Master"},

    # --- Sales / Master ---
    {"app_label": "sales", "model_name": "Customer", "field_name": "state",
     "label": "Customer - State of Supply", "module": "Sales", "category": "Master"},
    {"app_label": "sales", "model_name": "Customer", "field_name": "contact_type",
     "label": "Customer - Party Type", "module": "Sales", "category": "Master"},
    {"app_label": "sales", "model_name": "Customer", "field_name": "party_category",
     "label": "Customer - Party Category", "module": "Sales", "category": "Master"},

    # --- Purchase / Transaction ---
    {"app_label": "purchase", "model_name": "GeneralPurchase", "field_name": "calculation_based_on",
     "label": "General Purchase - Calculation Based On", "module": "Purchase", "category": "Transaction"},

    # --- Hatchery / Transaction ---
    {"app_label": "hatchery", "model_name": "EggPurchase", "field_name": "freight_type",
     "label": "Egg Purchase - Freight Type", "module": "Hatchery", "category": "Transaction"},
    {"app_label": "hatchery", "model_name": "EggPurchase", "field_name": "payment_mode",
     "label": "Egg Purchase - Payment Mode", "module": "Hatchery", "category": "Transaction"},
    {"app_label": "hatchery", "model_name": "ChickSale", "field_name": "freight_type",
     "label": "Chick Sale - Freight Type", "module": "Hatchery", "category": "Transaction"},
    {"app_label": "hatchery", "model_name": "ChickSale", "field_name": "payment_mode",
     "label": "Chick Sale - Payment Mode", "module": "Hatchery", "category": "Transaction"},
    {"app_label": "hatchery", "model_name": "DeliveryChallan", "field_name": "transport_mode",
     "label": "Delivery Challan - Transport Mode", "module": "Hatchery", "category": "Transaction"},
]

# (app_label, model_name, field_name) -> human_label
BINDABLE_FIELD_LOOKUP = {
    (f["app_label"], f["model_name"], f["field_name"]): f["label"] for f in BINDABLE_FIELDS
}

# (app_label, model_name, field_name) -> full entry dict (label/module/category)
BINDABLE_FIELD_INDEX = {
    (f["app_label"], f["model_name"], f["field_name"]): f for f in BINDABLE_FIELDS
}
