"""Spreadsheet import for master pages, reusing what the admin already has.

24 ``ModelResource`` classes already exist across the apps' ``admin.py`` files,
each with its own column names and foreign-key lookups. They work — but only
inside the Django admin, which is superuser-only, so nobody who actually
maintains a master can use them.

This exposes the same resources on the master pages themselves, gated by the
Web-Access matrix rather than by ``is_superuser``. Writing a second importer
would mean two sets of column rules to keep in step, and this codebase has
already paid that price elsewhere.

Two safeguards worth stating:

* An import is a bulk **add**, so it needs the tab's ``add`` right — viewing a
  master is not permission to rewrite it.
* Every import is dry-run first. The row errors come back before anything is
  written, so a bad column or a missing foreign key is a message rather than a
  half-finished master.
"""
from importlib import import_module

#: tab code -> "app.ResourceClassName". Only masters whose resource is a
#: straightforward column mapping; transaction resources are left out because
#: importing a voucher is not a spreadsheet problem.
IMPORTABLE = {
    "items": "inventory.admin.ItemResource",
    "customer": "sales.admin.CustomerResource",
    "sales_price_master": "sales.admin.SalesPriceMasterResource",
    "farmer_group": "broiler.admin.FarmerGroupResource",
    "branch_template": "broiler.admin.BranchResource",
    "supervisor_template": "broiler.admin.SupervisorResource",
    "broiler_line": "broiler.admin.BroilerLineResource",
    "branch_farm": "broiler.admin.BroilerFarmResource",
    "broiler_disease": "broiler.admin.BroilerDiseaseResource",
    "coa": "account.admin.ChartOfAccountResource",
    "bank_cash": "account.admin.BankCashMasterResource",
    "employee_list": "hr.admin.EmployeeResource",
    "employee_leave_details": "hr.admin.EmployeeLeaveResource",
    "employee_attendance": "hr.admin.AttendanceResource",
}

#: Masters with no resource yet — Item Category, Office/Warehouse and Supplier
#: among them. They need a ModelResource in their app's admin.py before they can
#: be listed above; a registry entry pointing at a class that does not exist
#: would render an Import button that fails when clicked.


def resource_for(tab_code):
    """The resource class registered for a tab, or None.

    Resolved lazily: the admin modules import a great deal, and a master page
    should not pay for that unless someone actually opens the import dialog.
    """
    path = IMPORTABLE.get(tab_code)
    if not path:
        return None
    module_path, _, name = path.rpartition(".")
    try:
        return getattr(import_module(module_path), name)
    except (ImportError, AttributeError):
        return None


def template_columns(tab_code):
    """Header row for the blank template someone downloads before filling it in.

    Taken from the resource itself, so the template and the parser can never
    disagree about what the columns are.
    """
    resource = resource_for(tab_code)
    if resource is None:
        return []
    return list(resource().get_export_headers())


def run_import(tab_code, file_obj, filename, commit=False):
    """Parse and validate a spreadsheet; write it only when ``commit``.

    Returns ``(result, errors)`` where errors is a list of
    ``(row number, message)`` — row numbers as the user sees them in the sheet,
    counting the header, because "row 7 is wrong" is only useful if it matches
    what is on their screen.
    """
    import tablib

    resource = resource_for(tab_code)
    if resource is None:
        return None, [(0, "This page does not support import.")]

    suffix = (filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in ("csv", "xlsx", "xls", "tsv"):
        return None, [(0, "Upload a .csv or .xlsx file.")]

    raw = file_obj.read()
    try:
        if suffix == "csv":
            dataset = tablib.Dataset().load(raw.decode("utf-8-sig"), format="csv")
        elif suffix == "tsv":
            dataset = tablib.Dataset().load(raw.decode("utf-8-sig"), format="tsv")
        else:
            dataset = tablib.Dataset().load(raw, format="xlsx")
    except Exception as exc:
        return None, [(0, f"Could not read the file: {exc}")]

    instance = resource()
    result = instance.import_data(dataset, dry_run=not commit,
                                  raise_errors=False, collect_failed_rows=True)

    errors = []
    for number, row in enumerate(result.rows, start=2):   # +1 header, +1 to 1-index
        for error in row.errors:
            errors.append((number, str(error.error)))
        for _field, messages in (row.validation_error.message_dict.items()
                                 if row.validation_error else []):
            errors.append((number, "; ".join(messages)))
    for error in result.base_errors:
        errors.append((0, str(error.error)))
    return result, errors
