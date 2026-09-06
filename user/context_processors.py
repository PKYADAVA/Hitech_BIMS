# user/context_processors.py
from .access import (
    allowed_view_tabs,
    breadcrumb_for,
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

    # Breadcrumb, computed from the same registry the nav uses so the two can
    # never disagree — and so no template has to carry its own trail.
    breadcrumb = breadcrumb_for(
        getattr(match, "url_name", None) if match else None, allowed_tabs)

    # The sidebar layout is a per-person choice, made on the UI Settings page
    # and stored on UserProfile.nav_layout. DS_SIDEBAR stays as the deployment
    # default for anyone who has never chosen -- so a server can start everyone
    # on the sidebar without each person opting in one at a time.
    #
    # Anonymous requests (the login page) never get the shell: there is no
    # profile to read and no menu to show.
    from django.conf import settings
    from .services.navigation import (nav_layout_for, role_label_for,
                                      sidebar_for)

    ds_shell = False
    if user is not None and user.is_authenticated:
        ds_shell = nav_layout_for(user) == "side"

    sidebar = (sidebar_for(user, getattr(match, "url_name", None) if match else None)
               if ds_shell else [])

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
        "breadcrumb": breadcrumb,
        "sidebar": sidebar,
        "ds_shell": ds_shell,
        "user_role_label": role_label_for(user),
        "app_version": getattr(settings, "APP_VERSION", ""),
        "pending_change_requests": pending_change_requests,
    }
