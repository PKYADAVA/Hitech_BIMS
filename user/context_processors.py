# user/context_processors.py
from .access import (
    allowed_view_tabs,
    allowed_nav_groups,
    allowed_section_groups,
    section_landing_urls,
    tab_action_perms,
    resolve_action,
    URLNAME_TO_TAB,
)


def web_access(request):
    """Expose Web-Access sets for nav-hiding and per-page button-hiding.

    ``allowed_tabs``     — tab codes the user may view (sub-nav links).
    ``allowed_nav``      — top-level navbar dropdowns that have any viewable tab.
    ``allowed_sections`` — "nav:Section" keys with any viewable tab (dropdown items).
    ``page_perms``       — the current page's action rights, e.g.
                           ``{% if page_perms.add %}`` to show an Add button.
    """
    user = getattr(request, "user", None)

    # Resolve the current page to its owning tab so templates can hide buttons.
    page_perms = {}
    match = getattr(request, "resolver_match", None)
    if match is not None:
        url_name = getattr(match, "url_name", None)
        tab = URLNAME_TO_TAB.get(url_name)
        if tab is None:
            resolved = resolve_action(url_name)
            tab = resolved[0] if resolved else None
        if tab is not None:
            page_perms = tab_action_perms(user, tab)

    allowed_tabs = allowed_view_tabs(user)

    # Pending change-request count for the navbar badge (only for users who
    # can see the Change Requests page at all).
    pending_change_requests = 0
    if "change_requests" in allowed_tabs:
        from hatchery.models import ChangeRequest
        pending_change_requests = ChangeRequest.objects.filter(status="pending").count()

    return {
        "allowed_tabs": allowed_tabs,
        "allowed_nav": allowed_nav_groups(user),
        "allowed_sections": allowed_section_groups(user),
        "section_url": section_landing_urls(user),
        "page_perms": page_perms,
        "pending_change_requests": pending_change_requests,
    }
