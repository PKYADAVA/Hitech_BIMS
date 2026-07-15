# user/access.py
"""
Single source of truth for the Web-Access permission matrix.

`MODULE_REGISTRY` mirrors the application navigation (main navbar + module
sub-navs). It is organised as Module -> Section -> Tab, following the navbar:
the top level is the navbar module (Broiler, Hatchery, …), then the sections
inside it (Master / Transactions / Reports / …), then each *tab* which maps to a
stable ``code`` that is also the primary Django URL name for that page.

The same registry drives three things:
  * the Web-Access editor matrix (what rows/columns to render),
  * nav-hiding (which links a group is allowed to see), and
  * the view-guard middleware (which url-names require a "view" permission).

Keeping it in one place means adding a screen to the ERP only needs a new tab
entry here for it to appear in the permission matrix and be enforced.
"""

# The action columns shown in the matrix (screenshot: View/Add/Edit/Delete/
# Print/Update/Favorite). Each becomes a boolean column on GroupTabPermission.
ACTIONS = ["view", "add", "edit", "delete", "print", "save", "update", "favorite"]

# Module (navbar dropdown) -> list of sections; each section -> list of tabs.
# tab = (code / url-name, human label). `extra_urls` (optional 3rd item) lists
# additional url-names that belong to the same tab so the view-guard treats
# e.g. a create/edit page as part of its parent tab.
MODULE_REGISTRY = [
    {
        "nav": "broiler",
        "label": "Broiler",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("farmer_group", "Farmer Group"),
                    ("region", "Region"),
                    ("branch_template", "Branch"),
                    ("supervisor_template", "Supervisor"),
                    ("broiler_line", "Broiler Line"),
                    ("branch_farm", "Broiler Farm"),
                    ("broiler_batch", "Broiler Batch"),
                    ("broiler_disease", "Broiler Disease"),
                ],
            },
        ],
    },
    {
        "nav": "hatchery",
        "label": "Hatchery",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("hatchery_master_list", "Hatchery Creation"),
                    ("setter_list", "Setter"),
                    ("hatcher_list", "Hatcher"),
                    ("expense_type_list", "Expense Type"),
                    ("hatchery_expense_list", "Hatchery Expense"),
                ],
            },
            {
                "label": "Transactions",
                "tabs": [
                    ("egg_purchase_list", "Egg Purchase"),
                    ("egg_grading_list", "Egg Grading"),
                    ("tray_set_list", "Tray Set"),
                    ("hatch_entry_list", "Hatch Entry"),
                    ("hatchery_list", "Hatch Register"),
                    ("delivery_challan_list", "Delivery Challan"),
                    ("chick_sale_list", "Chick Sale"),
                ],
            },
            {
                "label": "Environmental Monitoring",
                "tabs": [
                    ("env_dashboard", "Dashboard"),
                    ("env_hub_list", "Hubs"),
                    ("env_sensor_list", "Sensors"),
                    ("env_alert_list", "Alerts"),
                    ("env_tapo_account", "Tapo Account"),
                    ("env_default_thresholds", "Default Thresholds"),
                ],
            },
            {
                "label": "Reports",
                "tabs": [
                    ("egg_purchase_report", "Egg Purchase Report"),
                    ("incubation_report", "Incubation Report"),
                    ("hatchery_report", "Hatch Register Report"),
                    ("delivery_challan_report", "Delivery Challan Report"),
                    ("chick_sale_report", "Chick Sale Report"),
                ],
            },
        ],
    },
    {
        "nav": "purchase",
        "label": "Purchase",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("supplier", "Supplier"),
                    ("vendor_groups", "Vendor Groups"),
                    ("tax_master", "Tax Master"),
                ],
            },
            {
                "label": "Transactions",
                "tabs": [
                    ("purchase_order", "Create Purchase Order"),
                ],
            },
        ],
    },
    {
        "nav": "sales",
        "label": "Sales",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("customer_groups", "Customer Groups"),
                    ("customer", "Customer"),
                    ("sales_price_master", "Price Master"),
                ],
            },
        ],
    },
    {
        "nav": "account",
        "label": "Account",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("fin_year", "Financial Year"),
                    ("schedule", "Schedule"),
                    ("coa_category", "CoA Category"),
                    ("coa", "Chart of Accounts"),
                    ("bank_cash", "Bank / Cash Masters"),
                    ("company_profile", "Company Profile"),
                    ("terms", "Terms & Conditions"),
                ],
            },
        ],
    },
    {
        "nav": "inventory",
        "label": "Inventory",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("item_category", "Item Category"),
                    ("items", "Items"),
                    ("warehouse", "Warehouse"),
                ],
            },
        ],
    },
    {
        "nav": "hr",
        "label": "Human Resource",
        "sections": [
            {
                "label": "Employee Management",
                "tabs": [
                    ("employee_list", "Employee List"),
                ],
            },
            {
                "label": "Attendance",
                "tabs": [
                    ("leave_employee", "Leave Placed"),
                    ("employee_leave_details", "Leave Details"),
                    ("employee_attendance", "Attendance"),
                ],
            },
            {
                "label": "Payroll",
                "tabs": [
                    ("payroll", "Payroll"),
                ],
            },
        ],
    },
    {
        "nav": "user",
        "label": "User",
        "sections": [
            {
                "label": "User Management",
                "tabs": [
                    ("create_user", "Create User"),
                    ("assign_groups", "Assign Groups"),
                    ("user_groups", "Manage User Groups"),
                    ("user_analytics", "User Analytics"),
                ],
            },
        ],
    },
    {
        "nav": "notifications",
        "label": "Notifications",
        "sections": [
            {
                "label": "Master",
                "tabs": [
                    ("sms_templates", "SMS Templates"),
                ],
            },
        ],
    },
]


def iter_tabs():
    """Yield ``(nav, section_label, code, label, extra_urls)`` for every tab."""
    for module in MODULE_REGISTRY:
        for section in module["sections"]:
            for tab in section["tabs"]:
                code, label = tab[0], tab[1]
                extra_urls = tab[2] if len(tab) > 2 else ()
                yield module["nav"], section["label"], code, label, extra_urls


# All tab codes (url-names) that participate in the matrix.
ALL_TAB_CODES = {code for _nav, _s, code, _l, _e in iter_tabs()}

# navbar key -> set of tab codes underneath it (for hiding a whole dropdown).
NAV_GROUPS = {}
for _nav, _s, _code, _l, _e in iter_tabs():
    NAV_GROUPS.setdefault(_nav, set()).add(_code)

def section_key(nav, label):
    """Template-safe key for a section, e.g. ('hatchery','Environmental Monitoring')
    -> 'hatchery_environmental_monitoring'. Lets templates use plain dot-lookup
    (`{{ section_url.hatchery_transactions }}`) with no custom filter needed."""
    slug = (
        label.lower().replace("&", "and").replace("/", " ").replace("  ", " ").strip()
    )
    slug = "_".join(slug.split())
    return f"{nav}_{slug}"


# section-key -> set of tab codes (for hiding a section link inside a dropdown,
# e.g. hiding "Master" while still showing "Transactions").
SECTION_GROUPS = {}
for _nav, _s, _code, _l, _e in iter_tabs():
    SECTION_GROUPS.setdefault(section_key(_nav, _s), set()).add(_code)

# section-key -> ORDERED list of tab codes (registry order). Used to point a
# section's navbar link at the first tab the user actually has access to, so a
# partial grant (e.g. only "Hatch Register") doesn't land on a locked page.
SECTION_TABS = {}
for _module in MODULE_REGISTRY:
    for _section in _module["sections"]:
        SECTION_TABS[section_key(_module["nav"], _section["label"])] = [
            _t[0] for _t in _section["tabs"]
        ]

# Map every url-name (primary + extras) back to its owning tab code, so the
# view-guard can resolve the current request to a permission row. Url-names not
# present here are treated as unrestricted (open) to avoid accidental lockouts.
URLNAME_TO_TAB = {}
for _nav, _s, _code, _l, _extra in iter_tabs():
    URLNAME_TO_TAB[_code] = _code
    for _u in _extra:
        URLNAME_TO_TAB[_u] = _code


# ---------------------------------------------------------------------------
# Action (create / edit / delete) url-name resolution
# ---------------------------------------------------------------------------
# Create/edit/delete pages have their own url-names (e.g. ``customer_add``,
# ``branch_edit``). Their base part does NOT always match the tab code
# (``item_category`` -> ``category_create``; ``branch_template`` ->
# ``branch_create``), so we map the base explicitly. The trailing verb maps to
# a matrix action. This lets the middleware guard the *action* (add/edit/delete)
# on the owning tab, not just "view".
_ACTION_SUFFIX = {
    "add": "add", "create": "add", "new": "add",
    "edit": "edit", "update": "edit",
    "delete": "delete", "remove": "delete",
}

# action-url base  ->  owning tab code
_ACTION_BASE_TO_TAB = {
    # Broiler
    "region": "region",
    "branch": "branch_template",
    "supervisor": "supervisor_template",
    "broiler_line": "broiler_line",
    "broiler_farm": "branch_farm",
    "broiler_batch": "broiler_batch",
    "broiler_disease": "broiler_disease",
    "farmer_group": "farmer_group",
    # Hatchery master
    "hatchery_master": "hatchery_master_list",
    "setter": "setter_list",
    "hatcher": "hatcher_list",
    "expense_type": "expense_type_list",
    "hatchery_expense": "hatchery_expense_list",
    # Hatchery transactions
    "hatchery": "hatchery_list",
    "egg_purchase": "egg_purchase_list",
    "egg_grading": "egg_grading_list",
    "tray_set": "tray_set_list",
    "hatch_entry": "hatch_entry_list",
    "chick_sale": "chick_sale_list",
    "delivery_challan": "delivery_challan_list",
    # Environmental monitoring
    "env_hub": "env_hub_list",
    "env_sensor": "env_sensor_list",
    # Purchase
    "supplier": "supplier",
    "vendor_group": "vendor_groups",
    "tax_master": "tax_master",
    # Sales
    "customer": "customer",
    "customer_group": "customer_groups",
    "sales_price": "sales_price_master",
    # Account
    "chart_of_accounts": "coa",
    "coa_category": "coa_category",
    "financial_year": "fin_year",
    "schedule": "schedule",
    "terms_conditions": "terms",
    # Inventory
    "category": "item_category",
    "item": "items",
    "warehouse": "warehouse",
}


def resolve_action(url_name):
    """Return ``(tab_code, action)`` for a create/edit/delete url-name, else None."""
    if not url_name or "_" not in url_name:
        return None
    base, suffix = url_name.rsplit("_", 1)
    action = _ACTION_SUFFIX.get(suffix)
    if not action:
        return None
    tab = _ACTION_BASE_TO_TAB.get(base)
    if not tab:
        return None
    return tab, action


# ---------------------------------------------------------------------------
# Runtime permission checks
# ---------------------------------------------------------------------------

def _user_is_unrestricted(user):
    """Superusers and members of any 'admin' access-profile bypass all checks."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from .models import GroupAccessProfile
    return GroupAccessProfile.objects.filter(
        group__in=user.groups.all(), access_type="admin"
    ).exists()


def user_has_any_matrix_config(user):
    """True if any of the user's groups has at least one saved tab-permission.

    When a user belongs only to groups that were never configured in the
    Web-Access editor, the matrix is treated as *not yet applied* for them and
    everything is allowed. This keeps pre-existing accounts working until an
    admin actually locks a group down.
    """
    from .models import GroupTabPermission
    return GroupTabPermission.objects.filter(group__in=user.groups.all()).exists()


def _any_action_q():
    """Q matching a permission row that has *any* action ticked."""
    from django.db.models import Q
    q = Q()
    for a in ACTIONS:
        q |= Q(**{f"can_{a}": True})
    return q


def user_can(user, tab_code, action="view"):
    """Return True if *user* may perform *action* on the tab *tab_code*.

    ``view`` means "can reach the page" and is granted when the group has *any*
    permission on the tab — giving, say, only Add implies access to the page so
    the user can actually use that Add. Other actions check their own flag.
    """
    if _user_is_unrestricted(user):
        return True
    if not user or not user.is_authenticated:
        return False
    if not user_has_any_matrix_config(user):
        return True
    if action not in ACTIONS:
        action = "view"
    from .models import GroupTabPermission
    qs = GroupTabPermission.objects.filter(
        group__in=user.groups.all(), tab_code=tab_code
    )
    if action == "view":
        return qs.filter(_any_action_q()).exists()
    return qs.filter(**{f"can_{action}": True}).exists()


def tab_action_perms(user, tab_code):
    """Dict of ``{action: bool}`` for *tab_code* — used to hide/show page buttons."""
    return {a: user_can(user, tab_code, a) for a in ACTIONS}


def allowed_view_tabs(user):
    """Set of tab codes the user may *view* — used for nav-hiding."""
    if _user_is_unrestricted(user) or (
        user and user.is_authenticated and not user_has_any_matrix_config(user)
    ):
        return set(ALL_TAB_CODES)
    if not user or not user.is_authenticated:
        return set()
    from .models import GroupTabPermission
    # Any ticked action grants page access (see user_can).
    return set(
        GroupTabPermission.objects.filter(group__in=user.groups.all())
        .filter(_any_action_q())
        .values_list("tab_code", flat=True)
    )


def allowed_nav_groups(user):
    """Set of top-level navbar keys that have at least one viewable tab."""
    viewable = allowed_view_tabs(user)
    return {nav for nav, codes in NAV_GROUPS.items() if codes & viewable}


def allowed_section_groups(user):
    """Set of section-keys that have at least one viewable tab — used to
    hide individual section links (Master/Transactions/Reports/…) inside a
    navbar dropdown the user only partially has access to."""
    viewable = allowed_view_tabs(user)
    return {key for key, codes in SECTION_GROUPS.items() if codes & viewable}


def section_landing_urls(user):
    """Map section-key -> URL of the first tab in that section the user can
    view, so section navbar links never land on a page the user can't open."""
    from django.urls import reverse, NoReverseMatch

    viewable = allowed_view_tabs(user)
    urls = {}
    for key, codes in SECTION_TABS.items():
        for code in codes:
            if code in viewable:
                try:
                    urls[key] = reverse(code)
                except NoReverseMatch:
                    continue
                break
    return urls
