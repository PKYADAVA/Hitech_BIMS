from django.contrib import admin
from import_export import resources
from import_export.admin import ImportExportModelAdmin
from import_export.fields import Field
from import_export.widgets import ForeignKeyWidget
from inventory.models import Item, ItemCategory
from purchase.models import CreditTerm, VendorGroup
from .models import CustomerGroup, SalesPriceMaster, Customer


class SalesPriceMasterResource(resources.ModelResource):
    item_category = Field(
        attribute='item_category', column_name='item_category',
        widget=ForeignKeyWidget(ItemCategory, field='name'),
    )
    item = Field(
        attribute='item', column_name='item',
        widget=ForeignKeyWidget(Item, field='item_code'),
    )

    class Meta:
        model = SalesPriceMaster


class CustomerResource(resources.ModelResource):
    customer_group = Field(
        attribute='customer_group', column_name='customer_group',
        widget=ForeignKeyWidget(CustomerGroup, field='code'),
    )
    supplier_group = Field(
        attribute='supplier_group', column_name='supplier_group',
        widget=ForeignKeyWidget(VendorGroup, field='code'),
    )
    credit_term = Field(
        attribute='credit_term', column_name='credit_term',
        widget=ForeignKeyWidget(CreditTerm, field='term'),
    )

    class Meta:
        model = Customer
        # Mobile is the natural key (unique=True, required) — matching on it
        # means a row for a customer already on file is recognised as a
        # duplicate instead of hitting the DB's unique-constraint error.
        import_id_fields = ['mobile']

    def skip_row(self, instance, original, row, import_validation_errors=None):
        """Bulk import only ever adds new customers — it never silently
        overwrites one that already exists, so any row matching an existing
        mobile number is reported as a duplicate and left untouched."""
        if original and original.pk:
            return True
        return super().skip_row(instance, original, row, import_validation_errors)


class CustomerWebImportResource(CustomerResource):
    """Bulk upload from the Customer Master page itself (not the admin).

    Narrowed to exactly the fields the Add Customer web form collects
    (see sales.views._apply_posted_customer_fields) — a spreadsheet column
    the form has no field for would land in a column the web app can never
    show or edit again, so the two ways of adding a customer would quietly
    disagree about what got saved. The admin's own Import/Export keeps the
    full CustomerResource above; only the web page's importer is scoped down.
    """

    class Meta(CustomerResource.Meta):
        fields = (
            'name', 'address', 'mobile', 'mobile_2', 'customer_group', 'email',
            'pan_tin', 'aadhar', 'contact_type', 'party_category', 'gstin',
            'state', 'opening_balance', 'to_pay_to_receive', 'as_on_date',
            'note', 'credit_period', 'credit_limit', 'country', 'currency',
            'account_no', 'ifsc_code', 'bank_details', 'terms',
            'agreement_start_date', 'agreement_months', 'agreement_copy',
            'other_documents',
        )


@admin.register(CustomerGroup)
class CustomerGroupAdmin(ImportExportModelAdmin):
    list_display = ('code', 'description', 'currency', 'control_account', 'advance_account')
    search_fields = ('code', 'description', 'currency')
    list_filter = ('currency',)


@admin.register(SalesPriceMaster)
class SalesPriceMasterAdmin(ImportExportModelAdmin):
    resource_classes = [SalesPriceMasterResource]
    list_display = ('item_category', 'item', 'price', 'date')
    search_fields = ('item__name', 'item_category__name')
    list_filter = ('item_category', 'date')
    date_hierarchy = 'date'


@admin.register(Customer)
class CustomerAdmin(ImportExportModelAdmin):
    resource_classes = [CustomerResource]
    list_display = ('name', 'phone', 'mobile', 'contact_type', 'customer_group', 'supplier_group', 'credit_limit', 'state')
    search_fields = ('name', 'phone', 'mobile', 'gstin', 'state')
    list_filter = ('contact_type', 'state', 'customer_group', 'supplier_group')
    readonly_fields = ('gstin',)
    fieldsets = (
        (None, {
            'fields': ('name', 'address', 'place', 'phone', 'mobile', 'contact_type')
        }),
        ('Additional Information', {
            'fields': ('pan_tin', 'customer_group', 'supplier_group', 'credit_limit', 'credit_term', 'gstin', 'state', 'note', 'supplier_address'),
        }),
    )

