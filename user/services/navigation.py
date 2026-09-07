"""The sidebar, built from the nav registry rather than written out by hand.

``main_top_navbar.html`` is 1,063 lines of hand-written markup with a
``{% if code in allowed_tabs %}`` per link. It mirrors MODULE_REGISTRY but is
not generated from it, so the two drift: a tab added to the registry is
permitted by the guard and invisible in the nav until someone remembers the
template.

This reads the registry directly. A new tab appears in the sidebar the moment
it is registered, with the right module, the right section and the right
permission — because there is only one source for all three.
"""
from django.urls import NoReverseMatch, reverse

from user.access import MODULE_REGISTRY, allowed_view_tabs
from user.services.nav_icons import DEFAULT_TAB_ICON, TAB_ICONS

#: nav key -> Font Awesome icon, matched to the top navbar's own module icons
#: so a module is the same picture in either layout. The registry carries
#: structure, not looks, so the icons live here; a module with no entry still
#: renders, with a default.
NAV_ICONS = {
    "broiler": "fa-solid fa-egg",
    "hatchery": "fa-solid fa-kiwi-bird",
    "purchase": "fa-solid fa-cart-shopping",
    "sales": "fa-solid fa-indian-rupee-sign",
    "account": "fa-solid fa-file-invoice",
    "inventory": "fa-solid fa-warehouse",
    "hr": "fa-solid fa-users",
    "change_requests": "fa-solid fa-clipboard-check",
    "user": "fa-solid fa-users-gear",
    "notifications": "fa-solid fa-bell",
    "alerts": "fa-solid fa-bell-concierge",
    "environmental_monitoring": "fa-solid fa-temperature-half",
    "tracking": "fa-solid fa-gear",
}
DEFAULT_ICON = "fa-solid fa-folder"

#: Section heading -> icon, the same ones the top navbar's submenus use.
SECTION_ICONS = {
    "Master": "fas fa-sliders-h",
    "Transactions": "fas fa-exchange-alt",
    "Reports": "fas fa-chart-bar",
    "Growing Charges": "fas fa-hand-holding-dollar",
    "Farmer GC & Payment": "fas fa-file-invoice-dollar",
    "Farm Route Planner": "fas fa-route",
    "Environmental Monitoring": "fas fa-temperature-half",
    "Employee Management": "fas fa-user-cog",
    "Attendance": "fas fa-calendar-check",
    "Employee Trip And Route": "fas fa-route",
}
DEFAULT_SECTION_ICON = "fas fa-folder-open"


def nav_layout_for(user):
    """This person's chrome: ``"top"`` or ``"side"``.

    Profiles are created on demand, so most accounts have no row at all. Those
    fall back to the deployment default (``DS_SIDEBAR``), which lets a server
    start everyone on the sidebar without each person opting in one at a time.
    """
    from django.conf import settings

    from user.models import UserProfile

    default = "side" if getattr(settings, "DS_SIDEBAR", False) else "top"
    if user is None or not getattr(user, "is_authenticated", False):
        return "top"
    layout = (UserProfile.objects
              .filter(user=user)
              .values_list("nav_layout", flat=True)
              .first())
    return layout or default


def role_label_for(user):
    """A short description of who this is, for the account button.

    Their own profile role if it is set, otherwise the first group they belong
    to -- that is what the permission matrix actually keys off, so it is the
    most truthful one-word answer available. Superusers say Administrator when
    nothing else is on file.
    """
    from user.models import UserProfile

    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    role = (UserProfile.objects
            .filter(user=user)
            .values_list("role", flat=True)
            .first())
    if role:
        return role
    group = user.groups.values_list("name", flat=True).first()
    if group:
        return group
    return "Administrator" if user.is_superuser else "User"


def sidebar_for(user, active_url_name=None):
    """Modules the user may see, each with its sections and pages.

    Empty sections and empty modules are dropped rather than rendered as dead
    headings — a module the user has no tab in should not appear at all.
    """
    viewable = allowed_view_tabs(user)
    out = []

    for module in MODULE_REGISTRY:
        sections = []
        for section in module["sections"]:
            items = []
            for tab in section["tabs"]:
                code, label = tab[0], tab[1]
                if code not in viewable:
                    continue
                try:
                    url = reverse(code)
                except NoReverseMatch:
                    continue          # a tab code that is not a routable page
                extras = tab[2] if len(tab) > 2 else ()
                items.append({
                    "code": code,
                    "label": label,
                    "url": url,
                    "icon": TAB_ICONS.get(code, DEFAULT_TAB_ICON),
                    "active": active_url_name == code or active_url_name in extras,
                })
            if items:
                # `active` so the sidebar can open the one section holding the
                # page you are on, and leave the rest folded away.
                sections.append({
                    "label": section["label"],
                    "items": items,
                    "icon": SECTION_ICONS.get(section["label"], DEFAULT_SECTION_ICON),
                    "active": any(i["active"] for i in items),
                })
        if sections:
            out.append({
                "key": module["nav"],
                "label": module["label"],
                "icon": NAV_ICONS.get(module["nav"], DEFAULT_ICON),
                "sections": sections,
                "active": any(i["active"] for s in sections for i in s["items"]),
            })
    return out
