"""Why can this *user* do this, on this screen?

Every editor answers per group. Every support question is per user — "why can
Akash open this?" — and a user in three groups gets the union of three matrices
narrowed by two more gates, which nobody computes by eye. That gap produced
this feature's first bug report: the configuration was right, the member was a
superuser, and no page said so.

Nothing here decides anything. It calls the same functions the guards call and
reports which one said no, so an explanation can never drift from the rule it
claims to explain — the moment it computed its own answer it would become a
second implementation to keep in step.
"""
from __future__ import annotations

#: The gate that settled it, most specific first.
BYPASS = "Superuser or admin group — bypasses every gate"
NO_WEB = "No web permission for this action"
NO_MODULE = "The phone module is switched off in Mobile Access"
NO_SCREEN = "This action is unticked for the screen in Mobile Access"
NOT_ON_PHONE = "No screen in the phone app"
ALLOWED = "Allowed"


def granting_groups(user, tab_code, action):
    """The user's groups that grant this action on this tab, by name.

    The answer to "where does this come from?" — a user in several groups
    inherits the union, so naming the source is the difference between an
    explanation and a restatement.
    """
    from user.models import GroupTabPermission

    return list(
        GroupTabPermission.objects.filter(
            group__in=user.groups.all(), tab_code=tab_code,
            **{f"can_{action}": True})
        .values_list("group__name", flat=True)
        .order_by("group__name")
    )


def explain(user, tab_code, action="view"):
    """One verdict, with the gate that decided it.

    ``web`` is what the desktop allows; ``phone`` is that narrowed by Mobile
    Access. ``phone`` is ``None`` when the app has no screen for the tab —
    "not applicable", which is a different answer from "denied" and must not
    be shown as one.
    """
    from user.access import _user_is_unrestricted, user_can
    from user.services.mobile_access import (GOVERNED_TABS, MOBILE_ACTIONS,
                                             mobile_can)

    if _user_is_unrestricted(user):
        return {"tab": tab_code, "action": action, "web": True, "phone": True,
                "reason": BYPASS, "groups": []}

    web = bool(user_can(user, tab_code, action))
    on_phone = tab_code in GOVERNED_TABS and action in MOBILE_ACTIONS

    if not on_phone:
        return {"tab": tab_code, "action": action, "web": web, "phone": None,
                "reason": ALLOWED if web else NO_WEB,
                "groups": granting_groups(user, tab_code, action)}

    if not web:
        return {"tab": tab_code, "action": action, "web": False, "phone": False,
                "reason": NO_WEB, "groups": []}

    # Web says yes — so anything refusing now is one of the two phone gates.
    phone = bool(mobile_can(user, tab_code, action))
    reason = ALLOWED
    if not phone:
        from user.services.mobile_access import tab_is_mobile_allowed

        reason = NO_MODULE if not tab_is_mobile_allowed(user, tab_code) else NO_SCREEN

    return {"tab": tab_code, "action": action, "web": True, "phone": phone,
            "reason": reason, "groups": granting_groups(user, tab_code, action)}


def explain_all(user, actions=("view", "add", "edit", "delete"), query=""):
    """One row per tab: its label, and a verdict per action.

    Covers the whole registry rather than only what the user can reach — "why
    can they *not*" is asked at least as often as the other way round.
    """
    from user.access import iter_tabs
    from user.services.mobile_access import GOVERNED_TABS

    needle = (query or "").strip().lower()
    rows = []
    for nav, section, code, label, _extra in iter_tabs():
        if needle and needle not in label.lower() and needle not in code.lower():
            continue
        verdicts = [explain(user, code, action) for action in actions]
        rows.append({
            "nav": nav, "section": section, "code": code, "label": label,
            "on_phone": code in GOVERNED_TABS,
            "verdicts": verdicts,
            # Worth surfacing on the row: the phone disagreeing with the web is
            # exactly what Mobile Access is for, and the only case where the
            # two columns differ for a reason someone chose.
            "narrowed": any(v["web"] and v["phone"] is False for v in verdicts),
        })
    return rows


def summarise(user):
    """The one-line facts that explain most questions before the table does."""
    from user.access import (_user_is_unrestricted, allowed_nav_groups,
                             allowed_view_tabs, user_has_any_matrix_config)
    from user.services.mobile_access import mobile_preferences, screen_perms

    return {
        "groups": list(user.groups.values_list("name", flat=True).order_by("name")),
        "unrestricted": bool(_user_is_unrestricted(user)),
        "configured": bool(user_has_any_matrix_config(user)),
        "navs": sorted(allowed_nav_groups(user)),
        "tab_count": len(allowed_view_tabs(user)),
        "mobile_configured": mobile_preferences(user) is not None,
        "screens_configured": screen_perms(user) is not None,
    }
