from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from inventory.models import Warehouse


class FinancialYear(models.Model):
    """
    Model to manage financial years.
    
    This model represents a financial year with start and end dates.
    Only one financial year can be active at a time.
    """
    start_date = models.DateField(
        help_text=_("Start date of the financial year")
    )
    end_date = models.DateField(
        help_text=_("End date of the financial year")
    )
    is_active = models.BooleanField(
        default=False,
        help_text=_("Is this the active financial year?")
    )
    STATE_CHOICES = [
        ('Open', _('Open')),
        ('Closed', _('Closed')),
        ('Locked', _('Locked')),
    ]
    state = models.CharField(
        max_length=10,
        choices=STATE_CHOICES,
        default='Open',
        help_text=_("Open: postable. Closed: year-end run, reopenable. Locked: no changes allowed."),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last record update time")
    )

    def __str__(self):
        return f"FY {self.start_date.year}-{self.end_date.year}"

    def clean(self):
        """
        Ensure that end_date is later than start_date and only one active financial year exists.
        """
        if self.end_date <= self.start_date:
            raise ValidationError(_("End date must be after the start date."))

        if self.is_active:
            if FinancialYear.objects.filter(is_active=True).exclude(pk=self.pk).exists():
                raise ValidationError(_("There can only be one active financial year."))

    def save(self, *args, **kwargs):
        """
        Override save method to ensure only one active financial year exists.
        """
        if self.is_active:
            FinancialYear.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['-start_date']
        verbose_name = _("Financial Year")
        verbose_name_plural = _("Financial Years")
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]


class Schedule(models.Model):
    """
    Model to define the schedule used in the chart of accounts.
    
    Schedules are used to categorize accounts in the chart of accounts.
    """
    code = models.CharField(
        max_length=20, 
        unique=True, 
        help_text=_("Unique code for the account")
    )
    name = models.CharField(
        max_length=100, 
        unique=True, 
        help_text=_("Name of the schedule")
    )
    description = models.TextField(
        blank=True, 
        null=True, 
        help_text=_("Details about the schedule")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last updated at")
    )

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']
        verbose_name = _("Schedule")
        verbose_name_plural = _("Schedules")
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['name']),
        ]


class CoACategory(models.Model):
    """High-level sector grouping (Asset/Liability/etc.) used to organize the chart of accounts."""
    TYPE_CHOICES = [
        ('Asset', _('Asset')),
        ('Capital', _('Capital')),
        ('Expense', _('Expense')),
        ('Liability', _('Liability')),
        ('Revenue', _('Revenue')),
    ]

    code = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        blank=True,
        help_text=_("Auto-generated code for this category")
    )
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, help_text=_("Sector this category belongs to"))
    description = models.CharField(max_length=150, help_text=_("Name of the category"))
    is_active = models.BooleanField(default=True, help_text=_("Inactive categories are hidden from selection elsewhere"))
    is_locked = models.BooleanField(default=False, help_text=_("Locked records can't be edited or deleted"))
    created_at = models.DateTimeField(auto_now_add=True, help_text=_("Record created at"))
    updated_at = models.DateTimeField(auto_now=True, help_text=_("Last updated at"))

    def __str__(self):
        return f"{self.code} - {self.description}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.code:
            self.code = self._next_code()
            super().save(update_fields=['code'])

    @classmethod
    def _next_code(cls):
        """CAT-<n+1>, where n is the highest numeric suffix already in use.

        Not simply based on this row's own pk: categories are also bulk
        imported from CSV/Excel with pre-assigned codes that have gaps, so a
        pk-based code would collide with an already-imported higher number.
        """
        import re
        max_num = 0
        for existing_code in cls.objects.values_list('code', flat=True):
            match = re.match(r'CAT-(\d+)$', existing_code or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        return f"CAT-{max_num + 1:04d}"

    class Meta:
        ordering = ['code']
        verbose_name = _("CoA Category")
        verbose_name_plural = _("CoA Categories")
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['type']),
        ]


class AccountType(models.Model):
    """Fixed system table of fundamental account natures (Asset, Liability, ...).

    System rows are seeded by migration and can be neither deleted nor renamed;
    they drive report placement (BS/PL), the normal balance side, and the
    numeric range the automatic code generator allocates from.
    """
    NORMAL_BALANCE_CHOICES = [('Debit', _('Debit')), ('Credit', _('Credit'))]
    REPORT_CHOICES = [('BS', _('Balance Sheet')), ('PL', _('Profit & Loss'))]

    code = models.CharField(max_length=20, unique=True, help_text=_("Stable identifier, e.g. ASSET"))
    name = models.CharField(max_length=100, unique=True, help_text=_("Display name, e.g. Asset"))
    normal_balance = models.CharField(max_length=10, choices=NORMAL_BALANCE_CHOICES)
    report = models.CharField(max_length=2, choices=REPORT_CHOICES, help_text=_("Financial statement this type reports on"))
    code_range_start = models.PositiveIntegerField(help_text=_("Inclusive start of the auto-generated account code range"))
    code_range_end = models.PositiveIntegerField(help_text=_("Inclusive end of the auto-generated account code range"))
    is_system = models.BooleanField(default=True, help_text=_("System types cannot be deleted or renamed"))
    sort_order = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.name

    def clean(self):
        if self.pk and self.is_system:
            original = AccountType.objects.get(pk=self.pk)
            if original.is_system and (original.code != self.code or original.name != self.name):
                raise ValidationError(_("System account types cannot be renamed."))

    def delete(self, *args, **kwargs):
        if self.is_system:
            raise ValidationError(_("System account types cannot be deleted."))
        return super().delete(*args, **kwargs)

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = _("Account Type")
        verbose_name_plural = _("Account Types")


class AccountGroup(models.Model):
    """Configurable grouping under an account type (Current Assets, Sales, Tax, ...).

    Seeded with standard groups; users may add their own. Groups classify
    accounts for schedules/reports independent of the tree hierarchy.
    """
    name = models.CharField(max_length=100, unique=True)
    account_type = models.ForeignKey(AccountType, on_delete=models.PROTECT, related_name='groups')
    description = models.CharField(max_length=255, blank=True)
    is_system = models.BooleanField(default=False, help_text=_("Seeded groups referenced by templates"))
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['account_type__sort_order', 'name']
        verbose_name = _("Account Group")
        verbose_name_plural = _("Account Groups")


class ChartOfAccountManager(models.Manager):
    """Default manager hides soft-deleted accounts everywhere."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class ChartOfAccount(models.Model):
    """
    Company chart of accounts, held as a materialized-path tree.

    Generated per company from a CoATemplate by the COA generator service and
    editable afterwards. Legacy flat fields (type/status/schedule) are kept in
    sync so pre-existing hatchery/broiler FKs and filters keep working.
    """
    TYPE_CHOICES = [
        ('Asset', _('Asset')),
        ('Liability', _('Liability')),
        ('Equity', _('Equity')),
        ('Revenue', _('Revenue')),
        ('Income', _('Income')),
        ('Expense', _('Expense')),
        ('COGS', _('Cost Of Goods Sold')),
    ]
    STATUS_CHOICES = [
        ('Active', _('Active')),
        ('Inactive', _('Inactive')),
    ]
    OPENING_TYPE_CHOICES = [('Debit', _('Debit')), ('Credit', _('Credit'))]

    company = models.ForeignKey(
        'CompanyProfile',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='accounts',
        help_text=_("Owning company; every generated account belongs to one company"),
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='children',
        help_text=_("Parent group account in the tree"),
    )
    code = models.CharField(
        max_length=20,
        help_text=_("Account code, unique per company; auto-generated when blank"),
        blank=True,
    )
    description = models.CharField(
        max_length=255,
        help_text=_("Account name"),
    )
    account_type = models.ForeignKey(
        AccountType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='accounts',
    )
    account_group = models.ForeignKey(
        AccountGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounts',
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        help_text=_("Legacy flat type; kept in sync with account_type"),
    )
    control_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Control type for the account"),
    )
    schedule = models.ForeignKey(
        Schedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='accounts',
        help_text=_("Associated schedule"),
    )
    level = models.PositiveSmallIntegerField(default=0, editable=False)
    path = models.CharField(
        max_length=255,
        blank=True,
        editable=False,
        db_index=True,
        help_text=_("Materialized path of codes from root, e.g. 100000/110000/111000"),
    )
    currency = models.CharField(max_length=10, default='INR')
    opening_balance = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    opening_type = models.CharField(max_length=10, choices=OPENING_TYPE_CHOICES, default='Debit')
    is_group = models.BooleanField(default=False, help_text=_("Group nodes hold children and cannot be posted to"))
    is_postable = models.BooleanField(default=True, help_text=_("Only postable leaf accounts accept journal lines"))
    allow_manual_entry = models.BooleanField(default=True, help_text=_("Disallow to restrict posting to system modules"))
    system_generated = models.BooleanField(default=False, editable=False)
    system_role = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        help_text=_("Machine anchor (e.g. ACCOUNTS_RECEIVABLE) used by auto-ledger and tax engines"),
    )
    is_locked = models.BooleanField(default=False, help_text=_("Locked records can't be edited or deleted"))
    # Auto-ledger link back to the source record (customer, supplier, bank, ...)
    source_content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        related_name='ledger_accounts',
    )
    source_object_id = models.PositiveIntegerField(null=True, blank=True, editable=False)
    source = GenericForeignKey('source_content_type', 'source_object_id')
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='Active',
        help_text=_("Status of the account"),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', editable=False,
    )
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', editable=False,
    )
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', editable=False,
    )
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, help_text=_("Record created at"))
    updated_at = models.DateTimeField(auto_now=True, help_text=_("Last updated at"))

    objects = ChartOfAccountManager()
    all_objects = models.Manager()

    LEGACY_TYPE_MAP = {
        'ASSET': 'Asset',
        'LIABILITY': 'Liability',
        'EQUITY': 'Equity',
        'INCOME': 'Income',
        'EXPENSE': 'Expense',
        'COGS': 'COGS',
    }

    def __str__(self):
        return f"{self.code} - {self.description}"

    def clean(self):
        if self.parent_id:
            if not self.parent.is_group:
                raise ValidationError(_("Parent must be a group account."))
            if self.company_id and self.parent.company_id and self.company_id != self.parent.company_id:
                raise ValidationError(_("Parent account belongs to a different company."))
        if self.is_group and self.is_postable:
            raise ValidationError(_("Group accounts cannot be postable."))

    def save(self, *args, **kwargs):
        if self.is_group:
            self.is_postable = False
        if self.account_type_id and self.account_type.code in self.LEGACY_TYPE_MAP:
            self.type = self.LEGACY_TYPE_MAP[self.account_type.code]
        if self.parent_id:
            self.level = self.parent.level + 1
            self.path = f"{self.parent.path}/{self.code}"
        else:
            self.level = 0
            self.path = self.code
        super().save(*args, **kwargs)

    def soft_delete(self, user=None):
        """Mark deleted without removing the row; nothing is permanently deleted."""
        from django.utils import timezone
        if self.children.exists():
            raise ValidationError(_("Cannot delete an account that has child accounts."))
        self.deleted_at = timezone.now()
        self.deleted_by = user
        self.status = 'Inactive'
        super().save(update_fields=['deleted_at', 'deleted_by', 'status', 'updated_at'])

    class Meta:
        ordering = ['code']
        verbose_name = _("Chart of Account")
        verbose_name_plural = _("Chart of Accounts")
        constraints = [
            models.UniqueConstraint(fields=['company', 'code'], name='uniq_coa_company_code'),
        ]
        indexes = [
            models.Index(fields=['code']),
            models.Index(fields=['type']),
            models.Index(fields=['status']),
            models.Index(fields=['company', 'parent']),
            models.Index(fields=['company', 'system_role']),
            models.Index(fields=['company', 'is_group', 'status']),
        ]


class BankCode(models.Model):
    """
    Model to manage bank and cash codes.
    
    This model represents banks and their details.
    """
    bank_code = models.CharField(
        max_length=20, 
        unique=True, 
        help_text=_("Unique code for the bank")
    )
    bank_name = models.CharField(
        max_length=255, 
        help_text=_("Name of the bank")
    )
    sector = models.ForeignKey(
        Warehouse, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='banks',
        help_text=_("Sector of the bank")
    )
    micr = models.CharField(
        max_length=15, 
        blank=True, 
        null=True, 
        help_text=_("MICR code of the bank")
    )
    address = models.TextField(
        help_text=_("Address of the bank")
    )
    email = models.EmailField(
        blank=True, 
        null=True, 
        help_text=_("Email address of the bank")
    )
    phone = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        validators=[
            RegexValidator(
                regex=r'^\+?1?\d{9,15}$',
                message=_("Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed.")
            )
        ],
        help_text=_("Phone number of the bank")
    )
    fax = models.CharField(
        max_length=20, 
        blank=True, 
        null=True, 
        help_text=_("Fax number of the bank")
    )
    contact_person = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        help_text=_("Contact person at the bank")
    )
    created_at = models.DateTimeField(
        auto_now_add=True, 
        help_text=_("Record created at")
    )
    updated_at = models.DateTimeField(
        auto_now=True, 
        help_text=_("Last updated at")
    )

    def __str__(self):
        return f"{self.bank_code} - {self.bank_name}"

    class Meta:
        ordering = ['bank_name']
        verbose_name = _("Bank Code")
        verbose_name_plural = _("Bank Codes")
        indexes = [
            models.Index(fields=['bank_code']),
            models.Index(fields=['bank_name']),
        ]


class CompanyProfile(models.Model):
    """Single record holding the company's own letterhead/bank details, used on printed documents."""
    name = models.CharField(max_length=255, default="Company Name")
    address = models.TextField(blank=True)
    state = models.CharField(max_length=50, blank=True, help_text=_("Company's own state, for GST place-of-supply comparisons"))
    mobile = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    pan = models.CharField(max_length=10, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_no = models.CharField(max_length=50, blank=True)
    ifsc_code = models.CharField(max_length=20, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = _("Company Profile")
        verbose_name_plural = _("Company Profile")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # First company ever created becomes the default (pk=1) that get_solo
        # and legacy single-company code paths rely on; later companies get
        # their own pk so multi-company data stays isolated.
        if self._state.adding and self.pk is None and not CompanyProfile.objects.exists():
            self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class NarrationSettings(models.Model):
    """Single record of switches for the Auto Narration Engine (Journal Vouchers).

    Generation itself runs client-side; these toggles just control what the
    engine is allowed to weave into the sentence it builds.
    """
    enabled = models.BooleanField(default=True, help_text=_("Master on/off switch for auto narration"))
    include_amount = models.BooleanField(default=True, help_text=_("Mention the amount in generated narration"))
    include_reference = models.BooleanField(default=True, help_text=_("Mention the reference/bill number when present"))
    include_party = models.BooleanField(default=True, help_text=_("Mention the customer/supplier/party ledger name"))
    modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Narration Settings")
        verbose_name_plural = _("Narration Settings")

    def __str__(self):
        return "Narration Settings"

    def save(self, *args, **kwargs):
        if self._state.adding and self.pk is None and not NarrationSettings.objects.exists():
            self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _created = cls.objects.get_or_create(pk=1)
        return obj


class CoATemplate(models.Model):
    """Master COA blueprint per industry/country, copied per company at setup."""
    INDUSTRY_CHOICES = [
        ('General', _('General')),
        ('Trading', _('Trading')),
        ('Manufacturing', _('Manufacturing')),
        ('Retail', _('Retail')),
        ('Distribution', _('Distribution')),
        ('Poultry', _('Poultry')),
        ('Hatchery', _('Hatchery')),
        ('Agriculture', _('Agriculture')),
        ('Service', _('Service')),
        ('Hospital', _('Hospital')),
        ('Construction', _('Construction')),
    ]
    STATUS_CHOICES = [('Active', _('Active')), ('Inactive', _('Inactive'))]

    template_name = models.CharField(max_length=150, unique=True)
    industry = models.CharField(max_length=30, choices=INDUSTRY_CHOICES)
    country = models.CharField(max_length=2, default='IN', help_text=_("ISO country code driving tax account generation"))
    currency = models.CharField(max_length=10, default='INR')
    description = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Active')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.template_name

    class Meta:
        ordering = ['industry', 'template_name']
        verbose_name = _("CoA Template")
        verbose_name_plural = _("CoA Templates")
        indexes = [models.Index(fields=['industry', 'country', 'status'])]


class CoATemplateAccount(models.Model):
    """One node of a template's account hierarchy."""
    template = models.ForeignKey(CoATemplate, on_delete=models.CASCADE, related_name='accounts')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    account_code = models.CharField(max_length=20)
    account_name = models.CharField(max_length=255)
    account_type = models.ForeignKey(AccountType, on_delete=models.PROTECT, related_name='template_accounts')
    account_group = models.ForeignKey(AccountGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='template_accounts')
    level = models.PositiveSmallIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)
    is_group = models.BooleanField(default=False)
    is_postable = models.BooleanField(default=True)
    system_role = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    system_generated = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=CoATemplate.STATUS_CHOICES, default='Active')

    def __str__(self):
        return f"{self.account_code} - {self.account_name}"

    def save(self, *args, **kwargs):
        if self.is_group:
            self.is_postable = False
        self.level = self.parent.level + 1 if self.parent_id else 0
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['template', 'sort_order', 'account_code']
        verbose_name = _("CoA Template Account")
        verbose_name_plural = _("CoA Template Accounts")
        constraints = [
            models.UniqueConstraint(fields=['template', 'account_code'], name='uniq_template_account_code'),
        ]
        indexes = [
            models.Index(fields=['template', 'parent']),
            models.Index(fields=['template', 'level', 'sort_order']),
        ]


class CoAGenerationLog(models.Model):
    """Audit record of every COA generation run per company."""
    STATUS_CHOICES = [
        ('Running', _('Running')),
        ('Success', _('Success')),
        ('Failed', _('Failed')),
    ]
    company = models.ForeignKey('CompanyProfile', on_delete=models.CASCADE, related_name='coa_generation_logs')
    template = models.ForeignKey(CoATemplate, on_delete=models.SET_NULL, null=True, related_name='generation_logs')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Running')
    summary = models.JSONField(default=dict, blank=True, help_text=_("Per-step counts of created/skipped accounts"))
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f"{self.company} / {self.template} / {self.status}"

    class Meta:
        ordering = ['-started_at']
        verbose_name = _("CoA Generation Log")
        verbose_name_plural = _("CoA Generation Logs")


class AccountAuditLog(models.Model):
    """Immutable change trail for chart-of-account records (who/when/old/new)."""
    ACTION_CHOICES = [
        ('create', _('Create')),
        ('update', _('Update')),
        ('delete', _('Delete')),
        ('restore', _('Restore')),
        ('generate', _('Generate')),
        ('import', _('Import')),
        ('opening_balance', _('Opening Balance')),
    ]
    company = models.ForeignKey('CompanyProfile', on_delete=models.CASCADE, null=True, blank=True, related_name='account_audit_logs')
    account = models.ForeignKey(ChartOfAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.action} {self.account_id} by {self.user_id} at {self.timestamp:%Y-%m-%d %H:%M}"

    class Meta:
        ordering = ['-timestamp']
        verbose_name = _("Account Audit Log")
        verbose_name_plural = _("Account Audit Logs")
        indexes = [
            models.Index(fields=['company', 'timestamp']),
            models.Index(fields=['account', 'timestamp']),
        ]


class CostCenter(models.Model):
    """Analysis dimension for postings (department, farm, vehicle, ...)."""
    KIND_CHOICES = [
        ('Department', _('Department')),
        ('Warehouse', _('Warehouse')),
        ('Farm', _('Farm')),
        ('Project', _('Project')),
        ('Branch', _('Branch')),
        ('Vehicle', _('Vehicle')),
        ('ProductionUnit', _('Production Unit')),
    ]
    company = models.ForeignKey('CompanyProfile', on_delete=models.CASCADE, null=True, blank=True, related_name='cost_centers')
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children')
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='Department')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    class Meta:
        ordering = ['code']
        verbose_name = _("Cost Center")
        verbose_name_plural = _("Cost Centers")
        constraints = [
            models.UniqueConstraint(fields=['company', 'code'], name='uniq_costcenter_company_code'),
        ]


class Voucher(models.Model):
    """Journal voucher header. The only way value moves between accounts.

    Lifecycle: Draft (editable) -> Posted (immutable, gets its voucher number)
    -> Cancelled (kept forever with reason; lines stay for the audit trail).
    Posting requires an Open financial year covering the voucher date.
    """
    TYPE_CHOICES = [
        ('Journal', _('Journal')),
        ('Payment', _('Payment')),
        ('Receipt', _('Receipt')),
        ('Contra', _('Contra')),
        ('Sales', _('Sales')),
        ('Purchase', _('Purchase')),
        ('Opening', _('Opening')),
        ('Closing', _('Closing')),
    ]
    STATUS_CHOICES = [
        ('Draft', _('Draft')),
        ('Posted', _('Posted')),
        ('Cancelled', _('Cancelled')),
    ]

    company = models.ForeignKey('CompanyProfile', on_delete=models.CASCADE, related_name='vouchers')
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.PROTECT, related_name='vouchers')
    sector = models.ForeignKey(
        Warehouse, on_delete=models.SET_NULL, null=True, blank=True, related_name='vouchers',
        help_text=_("Office / branch this voucher belongs to"),
    )
    voucher_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default='Journal')
    voucher_no = models.CharField(
        max_length=30, null=True, blank=True, editable=False,
        help_text=_("Assigned when posted, e.g. JV/2026-27/0001"),
    )
    date = models.DateField()
    narration = models.TextField(blank=True)
    NARRATION_SOURCE_CHOICES = [
        ('AUTO', _('Auto-generated')),
        ('MANUAL', _('Manually edited')),
    ]
    auto_narration = models.TextField(
        blank=True,
        help_text=_("Last narration the auto-narration engine computed, kept even after manual edits"),
    )
    narration_source = models.CharField(
        max_length=10, choices=NARRATION_SOURCE_CHOICES, default='MANUAL',
        help_text=_("Whether the saved narration is the engine's text as-is or was hand-edited"),
    )
    narration_edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', editable=False,
        help_text=_("User who last overrode the auto-generated narration"),
    )
    narration_edited_at = models.DateTimeField(null=True, blank=True, editable=False)
    reference = models.CharField(max_length=100, blank=True, help_text=_("External document/bill reference"))
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Draft')
    system_generated = models.BooleanField(default=False, editable=False)
    total_debit = models.DecimalField(max_digits=18, decimal_places=2, default=0, editable=False)
    total_credit = models.DecimalField(max_digits=18, decimal_places=2, default=0, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    posted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    posted_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', editable=False)
    cancelled_at = models.DateTimeField(null=True, blank=True, editable=False)
    cancel_reason = models.CharField(max_length=255, blank=True)
    # Auto-posting link back to the source document (egg purchase, chick sale, ...)
    source_content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True, editable=False,
        related_name='vouchers',
    )
    source_object_id = models.PositiveIntegerField(null=True, blank=True, editable=False)
    source = GenericForeignKey('source_content_type', 'source_object_id')

    def __str__(self):
        return self.voucher_no or f"DRAFT-{self.pk}"

    class Meta:
        ordering = ['-date', '-id']
        verbose_name = _("Voucher")
        verbose_name_plural = _("Vouchers")
        constraints = [
            models.UniqueConstraint(
                fields=['company', 'financial_year', 'voucher_type', 'voucher_no'],
                name='uniq_voucher_number',
            ),
        ]
        indexes = [
            models.Index(fields=['company', 'date']),
            models.Index(fields=['company', 'voucher_type', 'status']),
            models.Index(fields=['company', 'status', 'date']),
            models.Index(fields=['source_content_type', 'source_object_id']),
        ]


class VoucherLine(models.Model):
    """One debit or credit leg of a voucher.

    ``date`` is denormalized from the header so ledger and trial-balance
    queries never join through the voucher table at scale.
    """
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='lines')
    line_no = models.PositiveSmallIntegerField(default=1)
    account = models.ForeignKey(ChartOfAccount, on_delete=models.PROTECT, related_name='voucher_lines')
    cost_center = models.ForeignKey(CostCenter, on_delete=models.PROTECT, null=True, blank=True, related_name='voucher_lines')
    date = models.DateField(editable=False, db_index=True)
    debit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    narration = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.voucher_id}/{self.line_no} {self.account_id} D{self.debit} C{self.credit}"

    def clean(self):
        if (self.debit or 0) < 0 or (self.credit or 0) < 0:
            raise ValidationError(_("Amounts cannot be negative."))
        if bool(self.debit) == bool(self.credit):
            raise ValidationError(_("Each line must have either a debit or a credit amount (not both, not neither)."))

    class Meta:
        ordering = ['voucher', 'line_no']
        verbose_name = _("Voucher Line")
        verbose_name_plural = _("Voucher Lines")
        indexes = [
            models.Index(fields=['account', 'date']),
        ]


class TermsConditions(models.Model):
    class PartyType(models.TextChoices):
        SUPPLIER = "Supplier", _("Supplier")
        CUSTOMER = "Customer", _("Customer")

    type = models.CharField(max_length=100, null=True, blank=True)
    party_type = models.CharField(max_length=20, choices=PartyType.choices, default=PartyType.CUSTOMER)
    condition = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.type or "Unnamed Terms and Condition"