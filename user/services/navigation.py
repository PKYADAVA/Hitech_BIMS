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

#: nav key -> Font Awesome icon. The registry carries structure, not looks, so
#: the icons live here; a module with no entry still renders, with a default.
NAV_ICONS = {
    "broiler": "fa-solid fa-egg",
    "hatchery": "fa-solid fa-kiwi-bird",
    "environmental_monitoring": "fa-solid fa-temperature-half",
    "inventory": "fa-solid fa-boxes-stacked",
    "purchase": "fa-solid fa-cart-shopping",
    "sales": "fa-solid fa-indian-rupee-sign",
    "account": "fa-solid fa-book",
    "hr": "fa-solid fa-users",
    "tracking": "fa-solid fa-location-dot",
    "user": "fa-solid fa-user-shield",
    "notifications": "fa-solid fa-bell",
    "alerts": "fa-solid fa-triangle-exclamation",
}
DEFAULT_ICON = "fa-solid fa-folder"


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
                    "active": active_url_name == code or active_url_name in extras,
                })
            if items:
                sections.append({"label": section["label"], "items": items})
        if sections:
            out.append({
                "key": module["nav"],
                "label": module["label"],
                "icon": NAV_ICONS.get(module["nav"], DEFAULT_ICON),
                "sections": sections,
                "active": any(i["active"] for s in sections for i in s["items"]),
            })
    return out
