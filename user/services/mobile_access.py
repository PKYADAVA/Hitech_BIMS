"""Mobile Access — which modules of the phone app a group may open.

The mobile client asks ``/api/v1/auth/permissions`` what it is allowed to show
and gates its home hub on the answer. Until this module existed that answer was
computed purely from the web tab matrix, so a group could not be given a screen
on the desktop and denied it on the phone: the two were the same permission.

This adds the second switch, and it only ever **narrows**. The effective set is

    web matrix  AND  Mobile Access

so enabling a module here cannot grant what the matrix withholds — the worst a
mistake on that page can do is hide something. That asymmetry is deliberate: an
access page that can only take away is safe to hand to an administrator, and it
means this file never has to be audited as a privilege-granting path.

Keys match ``MODULE_NAV`` in ``mobile/src/api/permissions.ts`` — the phone's
module keys — and each maps to the nav group of the same name in
``user.access.MODULE_REGISTRY`` (SMS is the one that differs: the phone calls it
``sms``, the registry calls it ``notifications``).
"""
from __future__ import annotations

#: ``(key, title, nav, icon, colour)`` for every module the phone can show.
#:
#: ``key``    — the mobile module key (matches MODULE_NAV in the RN app)
#: ``nav``    — the nav group in user.access.MODULE_REGISTRY that gates it
#: ``icon``   — Font Awesome class for the editor/preview
#: ``colour`` — accent used by the editor card
MOBILE_MODULES = [
    ("broiler",   "Broiler",    "broiler",       "fa-solid fa-kiwi-bird",     "#16a34a"),
    ("hatchery",  "Hatchery",   "hatchery",      "fa-solid fa-egg",           "#d97706"),
    ("inventory", "Inventory",  "inventory",     "fa-solid fa-boxes-stacked", "#0891b2"),
    ("sales",     "Sales",      "sales",         "fa-solid fa-cart-shopping", "#7c3aed"),
    ("purchase",  "Purchase",   "purchase",      "fa-solid fa-truck-field",   "#c2410c"),
    ("account",   "Account",    "account",       "fa-solid fa-book",          "#0369a1"),
    ("hr",        "HR",         "hr",            "fa-solid fa-user-tie",      "#be185d"),
    ("sms",       "SMS",        "notifications", "fa-solid fa-comment-sms",   "#0d9488"),
    ("user",      "Users",      "user",          "fa-solid fa-user-shield",   "#4f46e5"),
]

#: mobile module key -> nav group key
MODULE_NAV = {key: nav for key, _t, nav, _i, _c in MOBILE_MODULES}

#: nav group key -> mobile module key (the inverse; navs with no phone module
#: — e.g. tracking — are simply absent and are never gated by this page)
NAV_MODULE = {nav: key for key, nav in MODULE_NAV.items()}

ALL_KEYS = [key for key, *_rest in MOBILE_MODULES]

#: The actions the phone can be held to. Deliberately four, not the web
#: matrix's eight: ``save``/``update``/``favorite`` are already listed in
#: ``user.access.UNENFORCED_ACTIONS`` as ticks nothing reads, and there is no
#: printing on the phone. A column that controls nothing is worse than a
#: missing one — see the sort-order field this registry replaced.
MOBILE_ACTIONS = ["view", "add", "edit", "delete"]

#: ``(resource_key, tab_code)`` for every screen the phone app actually has.
#:
#: The resource key is the mobile client's own — it must match ``RESOURCE_TABS``
#: in ``mobile/src/api/permissions.ts``, and a test asserts the two agree so
#: drift is caught rather than discovered. Titles are NOT stored here: they come
#: from ``user.access.MODULE_REGISTRY`` at read time, so a screen renamed on the
#: web is renamed here too and there is no fourth list to keep in step.
#:
#: 142 web tabs exist; only these have a phone screen behind them. Listing the
#: rest would put ~350 checkboxes on the page that control nothing.
PHONE_SCREENS = [
    # Broiler
    ("broiler-daily-entries", "daily_entry_list"),
    ("broiler-medicine-vaccine", "medicine_entry_list"),
    ("broiler-bird-sales", "bird_sale_list"),
    ("broiler-sale-receipts", "bird_sale_receipt_list"),
    ("broiler-farms", "branch_farm"),
    ("broiler-sheds", "broiler_farm_shed"),
    ("broiler-batches", "broiler_batch"),
    ("broiler-farmer-groups", "farmer_group"),
    ("broiler-regions", "region"),
    ("broiler-branches", "branch_template"),
    ("broiler-lines", "broiler_line"),
    ("broiler-supervisors", "supervisor_template"),
    ("broiler-breeds", "breed"),
    ("broiler-breed-standards", "breed_standard"),
    ("broiler-diseases", "broiler_disease"),
    ("broiler-growing-charges", "growing_charge"),
    ("broiler-gc-settlements", "gc_settlement"),
    # Hatchery
    ("hatchery-egg-purchases", "egg_purchase_list"),
    ("hatchery-egg-gradings", "egg_grading_list"),
    ("hatchery-hatch-settings", "hatchery_list"),
    ("hatchery-tray-settings", "tray_set_list"),
    ("hatchery-hatch-entries", "hatch_entry_list"),
    ("hatchery-chick-sales", "chick_sale_list"),
    ("hatchery-delivery-challans", "delivery_challan_list"),
    ("hatchery-expenses", "hatchery_expense_list"),
    ("hatchery-expense-types", "expense_type_list"),
    ("hatchery-hatcheries", "hatchery_master_list"),
    ("hatchery-setters", "setter_list"),
    ("hatchery-hatchers", "hatcher_list"),
    # Inventory
    ("inventory-item-categories", "item_category"),
    ("inventory-items", "items"),
    ("inventory-price-list", "item_price_list"),
    ("inventory-sectors", "sector"),
    ("inventory-uom", "unit_of_measurement"),
    ("inventory-warehouses", "warehouse"),
    ("inventory-stock-transfers", "stock_transfer_list"),
    ("inventory-medicine-transfers", "medicine_transfer_list"),
    ("inventory-adjustments", "inventory_adjustment_list"),
    ("inventory-stock-issues", "stock_issue_list"),
    ("inventory-stock-receives", "stock_receive_list"),
    # Account
    ("account-financial-years", "fin_year"),
    ("account-chart-of-accounts", "coa"),
    ("account-bank-cash", "bank_cash"),
    ("account-organization-centres", "organization_centre"),
    ("account-company-profiles", "company_profile"),
    ("account-terms", "terms"),
    ("account-vouchers", "vouchers"),
    # Sales
    ("sales-invoices", "sales_invoice_list"),
    ("sales-receipts", "sales_receipt_list"),
    ("sales-customers", "customer"),
    ("sales-customer-groups", "customer_groups"),
    ("sales-prices", "sales_price_master"),
    # Purchase
    ("purchase-general-purchases", "general_purchase_list"),
    ("purchase-chicks-purchases", "chicks_purchase_list"),
    ("purchase-supplier-payments", "payment_list"),
    ("purchase-debit-notes", "debit_note_list"),
    ("purchase-credit-notes", "credit_note_list"),
    ("purchase-suppliers", "supplier"),
    ("purchase-vendor-groups", "vendor_groups"),
    ("purchase-tax-masters", "tax_master"),
    # HR
    ("hr-employees", "employee_list"),
    ("hr-attendance", "employee_attendance"),
    ("hr-leaves", "leave_employee"),
    ("hr-leave-dates", "employee_leave_details"),
    ("hr-payroll", "payroll"),
    ("hr-designations", "designation"),
    ("hr-groups", "employee_group"),
    # Users
    ("user-users", "create_user"),
    ("user-groups", "user_groups"),
    ("user-group-permissions", "assign_groups"),
    # SMS
    ("sms-templates", "sms_templates"),
    ("sms-messages", "sms_history"),
    ("sms-settings", "sms_settings"),
]

#: ``(report_key, tab_code)`` for the hub's report tiles.
#:
#: Kept separate from PHONE_SCREENS because a report is **view-only** — there
#: is nothing to add, edit or delete — so it gets one column, not four. Mixing
#: them into the screens list would put three permanently meaningless boxes on
#: every report row, which is the trap this whole registry is shaped to avoid.
#:
#: Must match ``REPORT_TABS`` in ``mobile/src/api/permissions.ts``; a test
#: compares them. ``mortality-trend`` is absent on purpose: no web report backs
#: it, so there is no permission to inherit and it stays ungated.
PHONE_REPORTS = [
    # Broiler
    ("live-flock", "live_flock_summary_report"),
    ("batch-summary", "broiler_batch_report"),
    ("chicks-placement", "chicks_placement_report"),
    ("day-record", "day_record_report"),
    ("feed-dispatch", "feed_dispatch_stock_report"),
    ("lifting", "lifting_report"),
    # Hatchery
    ("hatch-performance", "hatchery_report"),
    ("egg-intake", "egg_purchase_report"),
    ("incubation", "incubation_report"),
    ("delivery-challan", "delivery_challan_report"),
    ("chick-sale", "chick_sale_report"),
]

SCREEN_TABS = [tab for _key, tab in PHONE_SCREENS]
REPORT_TAB_LIST = [tab for _key, tab in PHONE_REPORTS]
RESOURCE_TABS = dict(PHONE_SCREENS)
REPORT_TABS = dict(PHONE_REPORTS)

#: Every tab Mobile Access has an opinion about. A tab outside this set has no
#: phone surface, so refusing it would deny something this page never claimed
#: to decide.
GOVERNED_TABS = set(SCREEN_TABS) | set(REPORT_TAB_LIST)


def _tab_labels():
    """``{tab_code: label}`` from the web registry — the single title source."""
    from user.access import iter_tabs

    return {code: label for _nav, _section, code, label, _extra in iter_tabs()}


def _tab_navs():
    """``{tab_code: nav}`` so a screen knows which phone module owns it."""
    from user.access import NAV_GROUPS

    return {code: nav for nav, codes in NAV_GROUPS.items() for code in codes}


def screens_by_module():
    """``[(module_key, title, [screen, …]), …]`` in MOBILE_MODULES order.

    Each screen is ``{"key", "tab", "title"}``. A phone screen whose tab is not
    in the web registry is dropped rather than shown label-less — that only
    happens when the two lists have drifted, which the registry test catches.
    """
    labels, navs = _tab_labels(), _tab_navs()
    by_nav = {}
    for source, kind, actions in ((PHONE_SCREENS, "screen", MOBILE_ACTIONS),
                                  (PHONE_REPORTS, "report", ["view"])):
        for key, tab in source:
            nav = navs.get(tab)
            if nav is None or tab not in labels:
                continue
            by_nav.setdefault(nav, []).append({
                "key": key, "tab": tab, "title": labels[tab],
                "kind": kind, "actions": actions,
            })

    out = []
    for key, title, nav, _icon, _colour in MOBILE_MODULES:
        # Screens first, then reports — the hub draws them in that order too.
        rows = sorted(by_nav.get(nav, []), key=lambda r: r["kind"] == "report")
        out.append((key, title, rows))
    return out


def all_modules():
    """``(key, title, nav, icon, colour)`` for every switchable module."""
    return list(MOBILE_MODULES)


def group_preferences(group):
    """``{module_key: position}`` for the modules this group enables.

    ``None`` when the group has no rows at all, which means *unconfigured* —
    every module its tabs allow, exactly as the app behaved before this page.
    Distinguishing "no rows" from "all rows off" matters: the second is a real
    choice (show nothing on the phone) and must not be read as the first.
    """
    from user.models import GroupMobileAccess

    rows = list(GroupMobileAccess.objects.filter(group=group))
    if not rows:
        return None
    return {r.module_key: r.position for r in rows if r.enabled}


def mobile_preferences(user):
    """``{module_key: position}`` across all of the user's groups, or ``None``.

    Union, at the earliest position any group gives it — the same way the tab
    matrix combines groups. ``None`` when no group the user belongs to has been
    configured, so an untouched system keeps working.
    """
    from user.models import GroupMobileAccess

    if not getattr(user, "is_authenticated", False):
        return None

    rows = list(
        GroupMobileAccess.objects.filter(group__in=user.groups.all())
        .values_list("module_key", "enabled", "position")
    )
    if not rows:
        return None

    out = {}
    for key, enabled, position in rows:
        if not enabled:
            continue
        if key not in out or position < out[key]:
            out[key] = position
    return out


def allowed_mobile_navs(user, web_navs):
    """Narrow ``web_navs`` (nav keys from the tab matrix) by Mobile Access.

    ``web_navs`` is what the matrix already permits; the result is what the
    phone should show. Navs with no mobile module — nothing on the phone maps
    to them — pass through untouched rather than being silently dropped.
    """
    prefs = mobile_preferences(user)
    if prefs is None:
        return set(web_navs)
    return {
        nav for nav in web_navs
        if nav not in NAV_MODULE or NAV_MODULE[nav] in prefs
    }


def group_screen_perms(group):
    """``{tab_code: {action: bool}}`` for one group, or ``None`` if unconfigured.

    ``None`` means no rows at all — keep whatever the web matrix allows, the
    same convention the module switch and the tab matrix both use.
    """
    from user.models import GroupMobileTabPermission

    rows = list(GroupMobileTabPermission.objects.filter(group=group))
    if not rows:
        return None
    return {
        r.tab_code: {a: getattr(r, f"can_{a}") for a in MOBILE_ACTIONS}
        for r in rows
    }


def screen_perms(user):
    """``{tab_code: {action: bool}}`` across the user's groups, or ``None``.

    Union: an action granted by any group is granted, matching how the tab
    matrix combines groups. ``None`` when no group of theirs has rows.
    """
    from user.models import GroupMobileTabPermission

    if not getattr(user, "is_authenticated", False):
        return None

    rows = list(
        GroupMobileTabPermission.objects.filter(group__in=user.groups.all())
        .values("tab_code", *[f"can_{a}" for a in MOBILE_ACTIONS])
    )
    if not rows:
        return None

    out = {}
    for row in rows:
        current = out.setdefault(row["tab_code"],
                                 {a: False for a in MOBILE_ACTIONS})
        for action in MOBILE_ACTIONS:
            if row[f"can_{action}"]:
                current[action] = True
    return out


def mobile_can(user, tab_code, action="view"):
    """The whole Mobile Access verdict for one screen and action.

    Three gates, all of which must agree, and none of which can grant on its
    own — the web matrix is checked by the caller, then the module switch, then
    the screen row. Unconfigured at either level means "no opinion", not "no".

    An action outside ``MOBILE_ACTIONS`` (print, save, favorite…) is not
    something this page claims to govern, so it passes through.
    """
    from user.access import _user_is_unrestricted

    if _user_is_unrestricted(user):
        return True
    if not tab_is_mobile_allowed(user, tab_code):
        return False
    if action not in MOBILE_ACTIONS:
        return True

    perms = screen_perms(user)
    if perms is None:
        return True
    if tab_code not in GOVERNED_TABS:
        return True             # no phone surface owns it — not ours to refuse
    if tab_code in REPORT_TABS.values() and action != "view":
        return True             # a report has only one meaningful action
    return bool(perms.get(tab_code, {}).get(action, False))


def tab_is_mobile_allowed(user, tab_code):
    """Is the module that owns ``tab_code`` switched on for this user's phone?

    Hiding a module has to close its API too. Hiding it only in the menu would
    leave every endpoint behind it callable by anything holding the token,
    which is the same hole ``MatrixPermission`` was written to close for the
    web matrix — an access page whose decisions stop at the UI is not an access
    page.

    Open by default in three cases, each matching a rule the web matrix already
    follows: an unrestricted user (superuser / admin group) bypasses; a user
    whose groups are unconfigured is unrestricted here too; and a tab owned by
    no nav — or by a nav with no phone module — is left alone rather than
    guessed at.
    """
    from user.access import NAV_GROUPS, _user_is_unrestricted

    if _user_is_unrestricted(user):
        return True

    prefs = mobile_preferences(user)
    if prefs is None:
        return True

    for nav, codes in NAV_GROUPS.items():
        if tab_code in codes:
            key = NAV_MODULE.get(nav)
            return True if key is None else key in prefs
    return True


def module_order(user):
    """Mobile module keys in the order the phone should lay out its home hub.

    Administrator order where one is configured, registry order otherwise —
    never alphabetical, which is what the endpoint used to return and is why
    the editor's sort column controlled nothing for its first version.

    Only modules the user can actually open are listed, so the client can lay
    out straight from this without re-filtering.
    """
    from user.access import allowed_nav_groups

    prefs = mobile_preferences(user)
    visible = allowed_mobile_navs(user, allowed_nav_groups(user))
    keys = [key for key in ALL_KEYS if MODULE_NAV[key] in visible]
    if prefs is None:
        return keys
    # Registry index breaks ties, so two modules sharing a position keep the
    # order the registry gives them rather than an arbitrary one.
    return sorted(keys, key=lambda k: (prefs.get(k, len(ALL_KEYS)), ALL_KEYS.index(k)))


def unbuilt_by_module():
    """``{module_key: [{tab, title}, …]}`` — web tabs with no phone screen yet.

    The editor lists these, greyed and without checkboxes, under each module.
    Leaving them out entirely was the honest choice for *ticks* — a box that
    decides nothing is worse than no box — but it left an administrator who had
    granted a tab on the web with no explanation for why it never appears here.
    Naming them, and saying plainly that the app has no screen for them, costs
    nothing and answers the question at the place it gets asked.

    Excluded: tabs already governed (they have real rows above), and navs with
    no phone module at all.
    """
    labels = _tab_labels()
    from user.access import NAV_GROUPS

    out = {}
    for key, _title, nav, _icon, _colour in MOBILE_MODULES:
        rows = [
            {"tab": tab, "title": labels.get(tab, tab)}
            for tab in sorted(NAV_GROUPS.get(nav, set()))
            if tab not in GOVERNED_TABS and tab in labels
        ]
        out[key] = sorted(rows, key=lambda r: r["title"])
    return out


def superuser_only_members(group):
    """``(members, superusers)`` counts, for the warning on the editor.

    Superusers bypass every gate here, so a group whose members are all
    superusers can be configured in full and change nothing. That is exactly
    how this feature's first bug report happened: the switches were right, the
    single member was a superuser, and the page said nothing.
    """
    members = list(group.user_set.values_list("is_superuser", flat=True))
    return len(members), sum(1 for is_super in members if is_super)


def modules_for_group(group, prefs_override=None):
    """Preview rows: what this group's phone home hub would show, and why not.

    Computed for the group rather than by impersonating a member, and each row
    says which gate stopped it — the tab matrix, or this page.

    ``prefs_override`` lets the editor preview the switches as they stand
    rather than as they were last saved; otherwise the button would show the
    database while you are mid-edit. ``{}`` is meaningful — nothing enabled.
    """
    from user.access import NAV_GROUPS
    from user.models import GroupTabPermission

    viewable = set(
        GroupTabPermission.objects.filter(group=group)
        .filter(_any_action())
        .values_list("tab_code", flat=True)
    )
    configured = GroupTabPermission.objects.filter(group=group).exists()
    prefs = group_preferences(group) if prefs_override is None else prefs_override

    rows = []
    for index, (key, title, nav, icon, colour) in enumerate(MOBILE_MODULES):
        # No matrix rows at all → unrestricted, same rule as allowed_view_tabs.
        by_matrix = (not configured) or bool(NAV_GROUPS.get(nav, set()) & viewable)
        by_mobile = prefs is None or key in prefs
        rows.append({
            "key": key,
            "title": title,
            "nav": nav,
            "icon": icon,
            "colour": colour,
            "shown": by_matrix and by_mobile,
            "position": (prefs or {}).get(key, index),
            "reason": (
                "" if by_matrix and by_mobile
                else "No permission on any of its screens" if not by_matrix
                else "Switched off here"
            ),
        })
    # Each module carries the screens that would appear inside it, so the
    # preview answers "and what can they do in there?" rather than stopping at
    # the hub — the question the matrix actually decides.
    screens = group_screen_perms(group)
    for row in rows:
        inside = next((s for k, _t, s in screens_by_module() if k == row["key"]), [])
        row["screens"] = [
            {
                "title": screen["title"],
                "actions": [
                    a for a in MOBILE_ACTIONS
                    if (screens is None or screens.get(screen["tab"], {}).get(a))
                    and (not configured or screen["tab"] in viewable)
                ],
            }
            for screen in inside
        ]
        row["screens"] = [s for s in row["screens"] if s["actions"]]

    rows.sort(key=lambda r: (not r["shown"], r["position"]))
    return rows


def _any_action():
    """Q matching a permission row with any action ticked.

    "View" means *any* action throughout this system — granting only Add still
    activates the page — so the preview has to use the same rule or it would
    disagree with what the phone actually does.
    """
    from django.db.models import Q

    from user.access import ACTIONS

    query = Q()
    for action in ACTIONS:
        query |= Q(**{f"can_{action}": True})
    return query
