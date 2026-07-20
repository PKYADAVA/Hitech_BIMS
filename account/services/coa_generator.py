"""COA generation engine.

Copies a :class:`~account.models.CoATemplate` hierarchy into a company's
chart of accounts, then layers country/industry system accounts on top
(tax, inventory, cash, bank, fixed assets, opening/P&L equity).

The whole run executes in one database transaction: any failure rolls back
every account while the :class:`~account.models.CoAGenerationLog` row (written
outside the transaction) records the failure. Re-running is idempotent -
accounts are matched by ``system_role`` first, then by code, and existing
matches are skipped rather than duplicated.
"""
import logging

from django.db import transaction
from django.utils import timezone

from account.models import (
    AccountType,
    BankCashMaster,
    ChartOfAccount,
    CoAGenerationLog,
    CoATemplateAccount,
)
from .code_generator import AccountCodeGenerator

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- specs
# (system_role, name, account_type code, parent system_role, is_group)

# Anchor groups the engine guarantees exist regardless of template contents.
ANCHOR_SPECS = [
    ("ASSETS_ROOT", "Assets", "ASSET", None, True),
    ("CURRENT_ASSETS", "Current Assets", "ASSET", "ASSETS_ROOT", True),
    ("FIXED_ASSETS", "Fixed Assets", "ASSET", "ASSETS_ROOT", True),
    ("CASH", "Cash & Cash Equivalents", "ASSET", "CURRENT_ASSETS", True),
    ("BANK_ACCOUNTS", "Bank Accounts", "ASSET", "CURRENT_ASSETS", True),
    ("ACCOUNTS_RECEIVABLE", "Accounts Receivable", "ASSET", "CURRENT_ASSETS", True),
    ("INVENTORY", "Inventory", "ASSET", "CURRENT_ASSETS", True),
    ("TAX_INPUT_GROUP", "GST Input & Tax Receivable", "ASSET", "CURRENT_ASSETS", True),
    ("LIABILITIES_ROOT", "Liabilities", "LIABILITY", None, True),
    ("CURRENT_LIABILITIES", "Current Liabilities", "LIABILITY", "LIABILITIES_ROOT", True),
    ("ACCOUNTS_PAYABLE", "Accounts Payable", "LIABILITY", "CURRENT_LIABILITIES", True),
    ("TAX_OUTPUT_GROUP", "Duties & Taxes", "LIABILITY", "CURRENT_LIABILITIES", True),
    ("SALARY_PAYABLE", "Salary Payable", "LIABILITY", "CURRENT_LIABILITIES", True),
    ("EQUITY_ROOT", "Equity", "EQUITY", None, True),
    ("INCOME_ROOT", "Income", "INCOME", None, True),
    ("SALES", "Sales", "INCOME", "INCOME_ROOT", True),
    ("OTHER_INCOME", "Other Income", "INCOME", "INCOME_ROOT", True),
    ("COGS_ROOT", "Cost Of Goods Sold", "COGS", None, True),
    ("EXPENSES_ROOT", "Expenses", "EXPENSE", None, True),
    ("ADMIN_EXPENSES", "Administrative Expenses", "EXPENSE", "EXPENSES_ROOT", True),
    ("FINANCIAL_EXPENSES", "Financial Expenses", "EXPENSE", "EXPENSES_ROOT", True),
    ("DEPRECIATION_EXPENSE", "Depreciation", "EXPENSE", "EXPENSES_ROOT", True),
    ("MISC_EXPENSES", "Miscellaneous Expenses", "EXPENSE", "EXPENSES_ROOT", True),
    ("EMPLOYEE_ADVANCE", "Employee Advances", "ASSET", "CURRENT_ASSETS", True),
]

# Country-specific tax ledgers, keyed by ISO country code.
TAX_SPECS = {
    "IN": [
        ("GST_INPUT_CGST", "Input CGST", "ASSET", "TAX_INPUT_GROUP", False),
        ("GST_INPUT_SGST", "Input SGST", "ASSET", "TAX_INPUT_GROUP", False),
        ("GST_INPUT_IGST", "Input IGST", "ASSET", "TAX_INPUT_GROUP", False),
        ("GST_RECEIVABLE", "GST Receivable", "ASSET", "TAX_INPUT_GROUP", False),
        ("TDS_RECEIVABLE", "TDS Receivable", "ASSET", "TAX_INPUT_GROUP", False),
        ("GST_OUTPUT_CGST", "Output CGST", "LIABILITY", "TAX_OUTPUT_GROUP", False),
        ("GST_OUTPUT_SGST", "Output SGST", "LIABILITY", "TAX_OUTPUT_GROUP", False),
        ("GST_OUTPUT_IGST", "Output IGST", "LIABILITY", "TAX_OUTPUT_GROUP", False),
        ("GST_PAYABLE", "GST Payable", "LIABILITY", "TAX_OUTPUT_GROUP", False),
        ("TDS_PAYABLE", "TDS Payable", "LIABILITY", "TAX_OUTPUT_GROUP", False),
        ("TCS_PAYABLE", "TCS Payable", "LIABILITY", "TAX_OUTPUT_GROUP", False),
        ("ROUND_OFF", "Round Off", "EXPENSE", "FINANCIAL_EXPENSES", False),
    ],
}

INVENTORY_SPECS = [
    ("INV_RAW_MATERIAL", "Raw Material", "ASSET", "INVENTORY", False),
    ("INV_FINISHED_GOODS", "Finished Goods", "ASSET", "INVENTORY", False),
    ("INV_FEED", "Feed", "ASSET", "INVENTORY", False),
    ("INV_MEDICINE", "Medicine", "ASSET", "INVENTORY", False),
    ("INV_PACKAGING", "Packaging", "ASSET", "INVENTORY", False),
    ("INV_BROILER", "Broiler Inventory", "ASSET", "INVENTORY", False),
    ("INV_EGG", "Egg Inventory", "ASSET", "INVENTORY", False),
    ("INV_CHICK", "Chick Inventory", "ASSET", "INVENTORY", False),
    ("INV_ADJUSTMENT", "Inventory Adjustment", "EXPENSE", "MISC_EXPENSES", False),
    ("INV_GAIN", "Inventory Gain", "INCOME", "OTHER_INCOME", False),
    ("INV_LOSS", "Inventory Loss", "EXPENSE", "MISC_EXPENSES", False),
    ("INV_STOCK_DIFFERENCE", "Stock Difference", "EXPENSE", "MISC_EXPENSES", False),
]

CASH_SPECS = [
    ("CASH_IN_HAND", "Cash In Hand", "ASSET", "CASH", False),
    ("PETTY_CASH", "Petty Cash", "ASSET", "CASH", False),
]

EQUITY_SPECS = [
    ("CAPITAL", "Capital Account", "EQUITY", "EQUITY_ROOT", False),
    ("RETAINED_EARNINGS", "Retained Earnings", "EQUITY", "EQUITY_ROOT", False),
    ("OPENING_BALANCE_EQUITY", "Opening Balance Equity", "EQUITY", "EQUITY_ROOT", False),
    ("PL_SUMMARY", "Profit & Loss Account", "EQUITY", "EQUITY_ROOT", False),
]

# Each fixed-asset class gets a cost account, accumulated depreciation and a
# depreciation expense ledger.
FIXED_ASSET_CLASSES = [
    "Land",
    "Building",
    "Machinery",
    "Vehicles",
    "Furniture",
    "Computers",
    "Electrical Equipment",
]


class CoAGeneratorService:
    def __init__(self, company, template, user=None, options=None):
        self.company = company
        self.template = template
        self.user = user
        options = options or {}
        self.with_tax = options.get("with_tax", True)
        self.with_inventory = options.get("with_inventory", True)
        self.with_cash = options.get("with_cash", True)
        self.with_banks = options.get("with_banks", True)
        self.with_fixed_assets = options.get("with_fixed_assets", True)
        self.codegen = AccountCodeGenerator(company)
        self.types = {t.code: t for t in AccountType.objects.all()}
        self.summary = {}

    # ------------------------------------------------------------------ API

    def generate(self):
        """Run the full pipeline; returns the generation log row."""
        log = CoAGenerationLog.objects.create(
            company=self.company, template=self.template, created_by=self.user,
        )
        try:
            with transaction.atomic():
                self._run()
        except Exception as exc:
            logger.exception("COA generation failed for company %s", self.company_id_str())
            log.status = "Failed"
            log.error = str(exc)
            log.finished_at = timezone.now()
            log.save(update_fields=["status", "error", "finished_at"])
            raise
        log.status = "Success"
        log.summary = self.summary
        log.finished_at = timezone.now()
        log.save(update_fields=["status", "summary", "finished_at"])
        return log

    def company_id_str(self):
        return str(getattr(self.company, "pk", self.company))

    # ------------------------------------------------------------ pipeline

    def _run(self):
        self.summary["template_accounts"] = self._copy_template()
        self.summary["anchors"] = self._create_from_specs(ANCHOR_SPECS)
        if self.with_tax:
            specs = TAX_SPECS.get((self.template.country or "IN").upper(), [])
            self.summary["tax_accounts"] = self._create_from_specs(specs)
        if self.with_inventory:
            self.summary["inventory_accounts"] = self._create_from_specs(INVENTORY_SPECS)
        if self.with_cash:
            self.summary["cash_accounts"] = self._create_from_specs(CASH_SPECS)
        if self.with_banks or self.with_cash:
            self.summary["bank_cash_accounts"] = self._generate_bank_cash_accounts()
        if self.with_fixed_assets:
            self.summary["fixed_assets"] = self._generate_fixed_assets()
        self.summary["equity_accounts"] = self._create_from_specs(EQUITY_SPECS)

    def _copy_template(self):
        created = skipped = 0
        id_map = {}
        nodes = (
            CoATemplateAccount.objects.filter(template=self.template, status="Active")
            .select_related("account_type", "account_group")
            .order_by("level", "sort_order", "account_code")
        )
        for node in nodes:
            parent = id_map.get(node.parent_id)
            existing = self._find_existing(node.system_role, node.account_code)
            if existing:
                id_map[node.id] = existing
                skipped += 1
                continue
            account = ChartOfAccount(
                company=self.company,
                parent=parent,
                code=node.account_code,
                description=node.account_name,
                account_type=node.account_type,
                account_group=node.account_group,
                currency=self.template.currency,
                is_group=node.is_group,
                is_postable=node.is_postable,
                system_generated=True,
                system_role=node.system_role,
                created_by=self.user,
            )
            account.save()
            id_map[node.id] = account
            created += 1
        return {"created": created, "skipped": skipped}

    def _create_from_specs(self, specs):
        created = skipped = 0
        for role, name, type_code, parent_role, is_group in specs:
            _, was_created = self._ensure_account(role, name, type_code, parent_role, is_group)
            created += int(was_created)
            skipped += int(not was_created)
        return {"created": created, "skipped": skipped}

    def _generate_bank_cash_accounts(self):
        """Backfill BankCashMaster rows that predate this company's COA —
        each files under Bank Accounts or Cash & Cash Equivalents per its
        ``is_cash`` flag. Rows created after the COA exists get their ledger
        from the post_save signal instead (account.signals.bank_cash_ledger)."""
        created = skipped = 0
        bank_parent, _ = self._ensure_account("BANK_ACCOUNTS", "Bank Accounts", "ASSET", "CURRENT_ASSETS", True)
        cash_parent, _ = self._ensure_account("CASH", "Cash & Cash Equivalents", "ASSET", "CURRENT_ASSETS", True)
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(BankCashMaster)
        for row in BankCashMaster.objects.all():
            if row.is_cash and not self.with_cash:
                continue
            if not row.is_cash and not self.with_banks:
                continue
            if ChartOfAccount.all_objects.filter(
                company=self.company, source_content_type=ct, source_object_id=row.pk
            ).exists():
                skipped += 1
                continue
            self._create_leaf(
                name=row.name,
                type_code="ASSET",
                parent=cash_parent if row.is_cash else bank_parent,
                source=row,
            )
            created += 1
        return {"created": created, "skipped": skipped}

    def _generate_fixed_assets(self):
        created = skipped = 0
        cost_parent, _ = self._ensure_account("FIXED_ASSETS", "Fixed Assets", "ASSET", "ASSETS_ROOT", True)
        accum_parent, _ = self._ensure_account(
            "ACCUM_DEPRECIATION", "Accumulated Depreciation", "ASSET", "FIXED_ASSETS", True
        )
        dep_parent, _ = self._ensure_account(
            "DEPRECIATION_EXPENSE", "Depreciation", "EXPENSE", "EXPENSES_ROOT", True
        )
        for asset in FIXED_ASSET_CLASSES:
            slug = asset.upper().replace(" ", "_")
            rows = [(f"FA_{slug}", asset, "ASSET", cost_parent)]
            if asset != "Land":  # land is never depreciated
                rows += [
                    (f"FA_{slug}_ACCUM_DEP", f"Accumulated Depreciation - {asset}", "ASSET", accum_parent),
                    (f"FA_{slug}_DEP_EXP", f"Depreciation - {asset}", "EXPENSE", dep_parent),
                ]
            for role, name, type_code, parent in rows:
                _, was_created = self._ensure_account(role, name, type_code, None, False, parent=parent)
                created += int(was_created)
                skipped += int(not was_created)
        return {"created": created, "skipped": skipped}

    # ----------------------------------------------------------- primitives

    def _find_existing(self, role, code=None):
        if role:
            match = ChartOfAccount.all_objects.filter(company=self.company, system_role=role).first()
            if match:
                return match
        if code:
            return ChartOfAccount.all_objects.filter(company=self.company, code=code).first()
        return None

    def _ensure_account(self, role, name, type_code, parent_role, is_group, parent=None):
        """Get-or-create an account by system role. Returns (account, created)."""
        existing = self._find_existing(role)
        if existing:
            return existing, False
        if parent is None and parent_role:
            parent = self._find_existing(parent_role)
            if parent is None:
                # Anchor specs are ordered parents-first, so this only happens
                # for malformed custom specs.
                raise ValueError(f"Parent anchor '{parent_role}' missing for '{role}'")
        account_type = self.types[type_code]
        account = ChartOfAccount(
            company=self.company,
            parent=parent,
            code=self.codegen.next_code(parent=parent, account_type=account_type, is_group=is_group),
            description=name,
            account_type=account_type,
            currency=self.template.currency,
            is_group=is_group,
            is_postable=not is_group,
            system_generated=True,
            system_role=role,
            created_by=self.user,
        )
        account.save()
        return account, True

    def _create_leaf(self, name, type_code, parent, source=None):
        account_type = self.types[type_code]
        account = ChartOfAccount(
            company=self.company,
            parent=parent,
            code=self.codegen.next_code(parent=parent, account_type=account_type, is_group=False),
            description=name,
            account_type=account_type,
            currency=self.template.currency,
            is_group=False,
            is_postable=True,
            system_generated=True,
            created_by=self.user,
        )
        if source is not None:
            account.source = source
        account.save()
        return account
