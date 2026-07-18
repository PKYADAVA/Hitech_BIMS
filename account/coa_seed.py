"""Seed data for the COA template engine.

Defines the standard Indian chart-of-accounts tree plus per-industry
overlays, and idempotent ``seed_*`` functions used by both the data
migration and the ``seed_coa_templates`` management command.

Node format: ``(code, name, type_code, group_name, system_role, children)``.
A node with children is a group (not postable); leaves are postable.
"""
from django.db import transaction

from account.models import AccountGroup, AccountType, CoATemplate, CoATemplateAccount

# --------------------------------------------------------------- account types

ACCOUNT_TYPES = [
    # code, name, normal_balance, report, range_start, range_end, sort
    ("ASSET", "Asset", "Debit", "BS", 100000, 199999, 1),
    ("LIABILITY", "Liability", "Credit", "BS", 200000, 299999, 2),
    ("EQUITY", "Equity", "Credit", "BS", 300000, 399999, 3),
    ("INCOME", "Income", "Credit", "PL", 400000, 499999, 4),
    ("COGS", "Cost Of Goods Sold", "Debit", "PL", 500000, 599999, 5),
    ("EXPENSE", "Expense", "Debit", "PL", 600000, 699999, 6),
]

ACCOUNT_GROUPS = [
    # name, type_code
    ("Current Assets", "ASSET"),
    ("Fixed Assets", "ASSET"),
    ("Inventory", "ASSET"),
    ("Current Liability", "LIABILITY"),
    ("Long Term Liability", "LIABILITY"),
    ("Tax", "LIABILITY"),
    ("Capital & Reserves", "EQUITY"),
    ("Sales", "INCOME"),
    ("Other Income", "INCOME"),
    ("Cost Of Goods Sold", "COGS"),
    ("Administrative Expense", "EXPENSE"),
    ("Selling & Distribution Expense", "EXPENSE"),
    ("Manufacturing Expense", "EXPENSE"),
    ("Financial Expense", "EXPENSE"),
    ("Depreciation", "EXPENSE"),
]

# Roles that are control groups even when seeded without children - ledgers
# (customers, banks, employees, ...) are attached under them later.
CONTAINER_ROLES = {
    "ASSETS_ROOT", "CURRENT_ASSETS", "FIXED_ASSETS", "ACCUM_DEPRECIATION",
    "CASH", "BANK_ACCOUNTS", "ACCOUNTS_RECEIVABLE", "INVENTORY", "TAX_INPUT_GROUP",
    "LIABILITIES_ROOT", "CURRENT_LIABILITIES", "LONG_TERM_LIABILITIES",
    "ACCOUNTS_PAYABLE", "TAX_OUTPUT_GROUP", "SALARY_PAYABLE", "EMPLOYEE_ADVANCE",
    "EQUITY_ROOT", "INCOME_ROOT", "SALES", "OTHER_INCOME",
    "COGS_ROOT", "COGS_GROUP", "EXPENSES_ROOT", "ADMIN_EXPENSES",
    "SELLING_EXPENSES", "FINANCIAL_EXPENSES", "DEPRECIATION_EXPENSE",
    "MISC_EXPENSES", "UTILITIES", "MANUFACTURING_EXPENSES",
    "FARM_EXPENSES", "HATCHERY_EXPENSES",
}

# ------------------------------------------------------------------- base tree

BASE_TREE = [
    ("100000", "Assets", "ASSET", None, "ASSETS_ROOT", [
        ("110000", "Current Assets", "ASSET", "Current Assets", "CURRENT_ASSETS", [
            ("111000", "Cash & Cash Equivalents", "ASSET", "Current Assets", "CASH", [
                ("111001", "Cash In Hand", "ASSET", "Current Assets", "CASH_IN_HAND", []),
                ("111002", "Petty Cash", "ASSET", "Current Assets", "PETTY_CASH", []),
            ]),
            ("112000", "Bank Accounts", "ASSET", "Current Assets", "BANK_ACCOUNTS", []),
            ("113000", "Accounts Receivable", "ASSET", "Current Assets", "ACCOUNTS_RECEIVABLE", []),
            ("114000", "Inventory", "ASSET", "Inventory", "INVENTORY", []),
            ("115000", "GST Input & Tax Receivable", "ASSET", "Current Assets", "TAX_INPUT_GROUP", []),
            ("116000", "Advances & Deposits", "ASSET", "Current Assets", None, [
                ("116001", "Employee Advances", "ASSET", "Current Assets", "EMPLOYEE_ADVANCE", []),
                ("116002", "Supplier Advances", "ASSET", "Current Assets", "SUPPLIER_ADVANCE", []),
                ("116003", "Security Deposits", "ASSET", "Current Assets", None, []),
            ]),
        ]),
        ("120000", "Fixed Assets", "ASSET", "Fixed Assets", "FIXED_ASSETS", [
            ("129000", "Accumulated Depreciation", "ASSET", "Fixed Assets", "ACCUM_DEPRECIATION", []),
        ]),
    ]),
    ("200000", "Liabilities", "LIABILITY", None, "LIABILITIES_ROOT", [
        ("210000", "Current Liabilities", "LIABILITY", "Current Liability", "CURRENT_LIABILITIES", [
            ("211000", "Accounts Payable", "LIABILITY", "Current Liability", "ACCOUNTS_PAYABLE", []),
            ("212000", "Duties & Taxes", "LIABILITY", "Tax", "TAX_OUTPUT_GROUP", []),
            ("213000", "Salary Payable", "LIABILITY", "Current Liability", "SALARY_PAYABLE", []),
            ("214000", "Other Payables", "LIABILITY", "Current Liability", None, [
                ("214001", "Expenses Payable", "LIABILITY", "Current Liability", None, []),
                ("214002", "Customer Advances", "LIABILITY", "Current Liability", "CUSTOMER_ADVANCE", []),
            ]),
        ]),
        ("220000", "Long Term Liabilities", "LIABILITY", "Long Term Liability", "LONG_TERM_LIABILITIES", [
            ("221000", "Secured Loans", "LIABILITY", "Long Term Liability", None, []),
            ("222000", "Unsecured Loans", "LIABILITY", "Long Term Liability", None, []),
        ]),
    ]),
    ("300000", "Equity", "EQUITY", None, "EQUITY_ROOT", [
        ("310000", "Capital Account", "EQUITY", "Capital & Reserves", "CAPITAL", []),
        ("320000", "Reserves & Surplus", "EQUITY", "Capital & Reserves", None, [
            ("320001", "Retained Earnings", "EQUITY", "Capital & Reserves", "RETAINED_EARNINGS", []),
        ]),
        ("330000", "Opening Balance Equity", "EQUITY", "Capital & Reserves", "OPENING_BALANCE_EQUITY", []),
        ("340000", "Profit & Loss Account", "EQUITY", "Capital & Reserves", "PL_SUMMARY", []),
        ("350000", "Drawings", "EQUITY", "Capital & Reserves", None, []),
    ]),
    ("400000", "Income", "INCOME", None, "INCOME_ROOT", [
        ("410000", "Sales", "INCOME", "Sales", "SALES", []),
        ("420000", "Other Income", "INCOME", "Other Income", "OTHER_INCOME", [
            ("420001", "Discount Received", "INCOME", "Other Income", None, []),
            ("420002", "Interest Income", "INCOME", "Other Income", "INTEREST_INCOME", []),
            ("420003", "Scrap Sales", "INCOME", "Other Income", None, []),
        ]),
    ]),
    ("500000", "Cost Of Goods Sold", "COGS", None, "COGS_ROOT", [
        ("510000", "Direct Costs", "COGS", "Cost Of Goods Sold", "COGS_GROUP", [
            ("510001", "Purchases", "COGS", "Cost Of Goods Sold", "PURCHASES", []),
            ("510002", "Purchase Returns", "COGS", "Cost Of Goods Sold", "PURCHASE_RETURNS", []),
            ("510003", "Freight Inward", "COGS", "Cost Of Goods Sold", "FREIGHT_INWARD_EXPENSE", []),
            ("510004", "Direct Wages", "COGS", "Cost Of Goods Sold", None, []),
        ]),
    ]),
    ("600000", "Expenses", "EXPENSE", None, "EXPENSES_ROOT", [
        ("610000", "Administrative Expenses", "EXPENSE", "Administrative Expense", "ADMIN_EXPENSES", [
            ("610001", "Salaries & Wages", "EXPENSE", "Administrative Expense", "SALARY_EXPENSE", []),
            ("610002", "Rent", "EXPENSE", "Administrative Expense", "RENT_EXPENSE", []),
            ("610003", "Office Expenses", "EXPENSE", "Administrative Expense", None, []),
            ("610004", "Printing & Stationery", "EXPENSE", "Administrative Expense", None, []),
            ("610005", "Telephone & Internet", "EXPENSE", "Administrative Expense", None, []),
            ("610006", "Professional Fees", "EXPENSE", "Administrative Expense", None, []),
            ("610007", "Repairs & Maintenance", "EXPENSE", "Administrative Expense", None, []),
        ]),
        ("620000", "Selling & Distribution Expenses", "EXPENSE", "Selling & Distribution Expense", "SELLING_EXPENSES", [
            ("620001", "Advertisement", "EXPENSE", "Selling & Distribution Expense", None, []),
            ("620002", "Freight Outward", "EXPENSE", "Selling & Distribution Expense", "FREIGHT_OUTWARD_EXPENSE", []),
            ("620003", "Sales Commission", "EXPENSE", "Selling & Distribution Expense", None, []),
            ("620004", "Discount Allowed", "EXPENSE", "Selling & Distribution Expense", None, []),
        ]),
        ("630000", "Financial Expenses", "EXPENSE", "Financial Expense", "FINANCIAL_EXPENSES", [
            ("630001", "Bank Charges", "EXPENSE", "Financial Expense", None, []),
            ("630002", "Interest Expense", "EXPENSE", "Financial Expense", "INTEREST_EXPENSE", []),
        ]),
        ("650000", "Depreciation", "EXPENSE", "Depreciation", "DEPRECIATION_EXPENSE", []),
        ("660000", "Miscellaneous Expenses", "EXPENSE", "Administrative Expense", "MISC_EXPENSES", []),
        ("670000", "Utilities", "EXPENSE", "Administrative Expense", "UTILITIES", [
            ("670001", "Electricity", "EXPENSE", "Administrative Expense", "ELECTRICITY_EXPENSE", []),
            ("670002", "Water", "EXPENSE", "Administrative Expense", None, []),
            ("670003", "Fuel & Diesel", "EXPENSE", "Administrative Expense", "FUEL_EXPENSE", []),
        ]),
    ]),
]

# ------------------------------------------------------------ industry overlays
# role of the parent node -> extra child nodes appended by that industry.

INDUSTRY_OVERLAYS = {
    "General": {},
    "Trading": {
        "SALES": [
            ("410001", "Trade Sales", "INCOME", "Sales", None, []),
            ("410002", "Sales Returns", "INCOME", "Sales", "SALES_RETURNS", []),
        ],
        "INVENTORY": [
            ("114001", "Stock In Trade", "ASSET", "Inventory", None, []),
        ],
    },
    "Retail": {
        "SALES": [
            ("410001", "Counter Sales", "INCOME", "Sales", None, []),
            ("410002", "Online Sales", "INCOME", "Sales", None, []),
            ("410003", "Sales Returns", "INCOME", "Sales", "SALES_RETURNS", []),
        ],
        "INVENTORY": [
            ("114001", "Stock In Trade", "ASSET", "Inventory", None, []),
        ],
        "SELLING_EXPENSES": [
            ("620005", "Packing Expenses", "EXPENSE", "Selling & Distribution Expense", None, []),
        ],
    },
    "Distribution": {
        "SALES": [
            ("410001", "Distribution Sales", "INCOME", "Sales", None, []),
            ("410002", "Scheme Incentives", "INCOME", "Sales", None, []),
            ("410003", "Sales Returns", "INCOME", "Sales", "SALES_RETURNS", []),
        ],
        "INVENTORY": [
            ("114001", "Stock In Trade", "ASSET", "Inventory", None, []),
        ],
        "SELLING_EXPENSES": [
            ("620005", "Vehicle Running Expenses", "EXPENSE", "Selling & Distribution Expense", None, []),
        ],
    },
    "Manufacturing": {
        "INVENTORY": [
            ("114001", "Raw Material", "ASSET", "Inventory", "INV_RAW_MATERIAL", []),
            ("114002", "Work In Progress", "ASSET", "Inventory", "INV_WIP", []),
            ("114003", "Finished Goods", "ASSET", "Inventory", "INV_FINISHED_GOODS", []),
            ("114004", "Consumables & Spares", "ASSET", "Inventory", None, []),
        ],
        "SALES": [
            ("410001", "Finished Goods Sales", "INCOME", "Sales", None, []),
            ("410002", "Job Work Income", "INCOME", "Sales", None, []),
        ],
        "EXPENSES_ROOT": [
            ("640000", "Manufacturing Expenses", "EXPENSE", "Manufacturing Expense", "MANUFACTURING_EXPENSES", [
                ("640001", "Power & Fuel", "EXPENSE", "Manufacturing Expense", None, []),
                ("640002", "Factory Wages", "EXPENSE", "Manufacturing Expense", None, []),
                ("640003", "Consumables", "EXPENSE", "Manufacturing Expense", None, []),
                ("640004", "Factory Repairs", "EXPENSE", "Manufacturing Expense", None, []),
            ]),
        ],
    },
    "Poultry": {
        "SALES": [
            ("410001", "Broiler Sales", "INCOME", "Sales", None, []),
            ("410002", "Cull Bird Sales", "INCOME", "Sales", None, []),
            ("410003", "Manure Sales", "INCOME", "Sales", None, []),
        ],
        "INVENTORY": [
            ("114001", "Broiler Inventory", "ASSET", "Inventory", "INV_BROILER", []),
            ("114002", "Feed", "ASSET", "Inventory", "INV_FEED", []),
            ("114003", "Medicine", "ASSET", "Inventory", "INV_MEDICINE", []),
        ],
        "COGS_GROUP": [
            ("510005", "Chick Purchases", "COGS", "Cost Of Goods Sold", None, []),
            ("510006", "Feed Purchases", "COGS", "Cost Of Goods Sold", None, []),
            ("510007", "Medicine Purchases", "COGS", "Cost Of Goods Sold", None, []),
        ],
        "EXPENSES_ROOT": [
            ("640000", "Farm Expenses", "EXPENSE", "Manufacturing Expense", "FARM_EXPENSES", [
                ("640001", "Vaccination", "EXPENSE", "Manufacturing Expense", None, []),
                ("640002", "Litter & Bedding", "EXPENSE", "Manufacturing Expense", None, []),
                ("640003", "Mortality Loss", "EXPENSE", "Manufacturing Expense", None, []),
                ("640004", "Farm Labour", "EXPENSE", "Manufacturing Expense", None, []),
                ("640005", "Brooding Expenses", "EXPENSE", "Manufacturing Expense", None, []),
            ]),
        ],
    },
    "Hatchery": {
        "SALES": [
            ("410001", "Chick Sales", "INCOME", "Sales", None, []),
            ("410002", "Hatching Egg Sales", "INCOME", "Sales", None, []),
            ("410003", "Rejected Egg Sales", "INCOME", "Sales", None, []),
        ],
        "INVENTORY": [
            ("114001", "Egg Inventory", "ASSET", "Inventory", "INV_EGG", []),
            ("114002", "Chick Inventory", "ASSET", "Inventory", "INV_CHICK", []),
            ("114003", "Feed", "ASSET", "Inventory", "INV_FEED", []),
            ("114004", "Medicine", "ASSET", "Inventory", "INV_MEDICINE", []),
        ],
        "COGS_GROUP": [
            ("510005", "Egg Purchases", "COGS", "Cost Of Goods Sold", None, []),
        ],
        "EXPENSES_ROOT": [
            ("640000", "Hatchery Expenses", "EXPENSE", "Manufacturing Expense", "HATCHERY_EXPENSES", [
                ("640001", "Incubation Power", "EXPENSE", "Manufacturing Expense", None, []),
                ("640002", "Hatchery Consumables", "EXPENSE", "Manufacturing Expense", None, []),
                ("640003", "Candling Loss", "EXPENSE", "Manufacturing Expense", None, []),
                ("640004", "Hatchery Labour", "EXPENSE", "Manufacturing Expense", None, []),
            ]),
        ],
    },
    "Agriculture": {
        "SALES": [
            ("410001", "Crop Sales", "INCOME", "Sales", None, []),
            ("410002", "Produce Sales", "INCOME", "Sales", None, []),
        ],
        "INVENTORY": [
            ("114001", "Seeds", "ASSET", "Inventory", None, []),
            ("114002", "Fertilizer", "ASSET", "Inventory", None, []),
            ("114003", "Pesticides", "ASSET", "Inventory", None, []),
            ("114004", "Harvested Produce", "ASSET", "Inventory", None, []),
        ],
        "EXPENSES_ROOT": [
            ("640000", "Cultivation Expenses", "EXPENSE", "Manufacturing Expense", "FARM_EXPENSES", [
                ("640001", "Irrigation", "EXPENSE", "Manufacturing Expense", None, []),
                ("640002", "Farm Labour", "EXPENSE", "Manufacturing Expense", None, []),
                ("640003", "Equipment Hire", "EXPENSE", "Manufacturing Expense", None, []),
            ]),
        ],
    },
    "Service": {
        "SALES": [
            ("410001", "Service Revenue", "INCOME", "Sales", None, []),
            ("410002", "Consulting Income", "INCOME", "Sales", None, []),
            ("410003", "AMC Income", "INCOME", "Sales", None, []),
        ],
        "CURRENT_ASSETS": [
            ("117000", "Unbilled Revenue", "ASSET", "Current Assets", None, []),
        ],
        "COGS_GROUP": [
            ("510005", "Subcontract Charges", "COGS", "Cost Of Goods Sold", None, []),
        ],
    },
    "Hospital": {
        "SALES": [
            ("410001", "OPD Income", "INCOME", "Sales", None, []),
            ("410002", "IPD Income", "INCOME", "Sales", None, []),
            ("410003", "Pharmacy Sales", "INCOME", "Sales", None, []),
            ("410004", "Laboratory Income", "INCOME", "Sales", None, []),
        ],
        "INVENTORY": [
            ("114001", "Medicines", "ASSET", "Inventory", "INV_MEDICINE", []),
            ("114002", "Medical Consumables", "ASSET", "Inventory", None, []),
        ],
        "EXPENSES_ROOT": [
            ("640000", "Medical Expenses", "EXPENSE", "Administrative Expense", None, [
                ("640001", "Doctor Fees", "EXPENSE", "Administrative Expense", None, []),
                ("640002", "Lab Charges", "EXPENSE", "Administrative Expense", None, []),
                ("640003", "Bio-Medical Waste Disposal", "EXPENSE", "Administrative Expense", None, []),
            ]),
        ],
    },
    "Construction": {
        "SALES": [
            ("410001", "Contract Revenue", "INCOME", "Sales", None, []),
            ("410002", "Work Certified", "INCOME", "Sales", None, []),
        ],
        "CURRENT_ASSETS": [
            ("117000", "Work In Progress (Contracts)", "ASSET", "Current Assets", "INV_WIP", []),
            ("118000", "Retention Money Receivable", "ASSET", "Current Assets", None, []),
        ],
        "COGS_GROUP": [
            ("510005", "Material Consumed", "COGS", "Cost Of Goods Sold", None, []),
            ("510006", "Subcontractor Charges", "COGS", "Cost Of Goods Sold", None, []),
        ],
        "EXPENSES_ROOT": [
            ("640000", "Site Expenses", "EXPENSE", "Manufacturing Expense", None, [
                ("640001", "Site Labour", "EXPENSE", "Manufacturing Expense", None, []),
                ("640002", "Equipment Rental", "EXPENSE", "Manufacturing Expense", None, []),
                ("640003", "Site Utilities", "EXPENSE", "Manufacturing Expense", None, []),
            ]),
        ],
    },
}


# ----------------------------------------------------------------- seed logic

def seed_account_types():
    for code, name, balance, report, start, end, sort in ACCOUNT_TYPES:
        AccountType.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "normal_balance": balance,
                "report": report,
                "code_range_start": start,
                "code_range_end": end,
                "is_system": True,
                "sort_order": sort,
            },
        )


def seed_account_groups():
    types = {t.code: t for t in AccountType.objects.all()}
    for name, type_code in ACCOUNT_GROUPS:
        AccountGroup.objects.update_or_create(
            name=name,
            defaults={"account_type": types[type_code], "is_system": True},
        )


def _merge_tree(base, overlays):
    """Return a deep copy of the base tree with overlay children appended."""

    def walk(nodes):
        result = []
        for code, name, type_code, group, role, children in nodes:
            children = walk(children)
            if role and role in overlays:
                children = children + [c for c in walk(overlays[role])]
            result.append((code, name, type_code, group, role, children))
        return result

    return walk(base)


def _create_nodes(template, nodes, types, groups, parent=None, counter=None):
    counter = counter if counter is not None else [0]
    for code, name, type_code, group, role, children in nodes:
        counter[0] += 10
        is_group = bool(children) or role in CONTAINER_ROLES
        node = CoATemplateAccount.objects.create(
            template=template,
            parent=parent,
            account_code=code,
            account_name=name,
            account_type=types[type_code],
            account_group=groups.get(group),
            sort_order=counter[0],
            is_group=is_group,
            is_postable=not is_group,
            system_role=role,
        )
        _create_nodes(template, children, types, groups, parent=node, counter=counter)


@transaction.atomic
def seed_coa_templates(rebuild=False):
    """Create one standard template per industry. Idempotent.

    With ``rebuild=True`` existing template account rows are replaced with the
    current seed definition (the template row itself is kept).
    """
    seed_account_types()
    seed_account_groups()
    types = {t.code: t for t in AccountType.objects.all()}
    groups = {g.name: g for g in AccountGroup.objects.all()}

    created = []
    for industry, _label in CoATemplate.INDUSTRY_CHOICES:
        template, template_created = CoATemplate.objects.get_or_create(
            template_name=f"India {industry} Standard",
            defaults={
                "industry": industry,
                "country": "IN",
                "currency": "INR",
                "description": f"Standard Indian chart of accounts for {industry.lower()} businesses.",
            },
        )
        if not template_created and not rebuild:
            continue
        if rebuild:
            template.accounts.all().delete()
        tree = _merge_tree(BASE_TREE, INDUSTRY_OVERLAYS.get(industry, {}))
        _create_nodes(template, tree, types, groups)
        created.append(template.template_name)
    return created
