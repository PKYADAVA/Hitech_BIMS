"""Template context for the notification bell.

The bell needs to know whether this user wants a sound and a desktop popup
*before* the first alert of the session arrives. Fetching that over the API
would mean the very first notification — often the most urgent one, since the
badge was empty until then — arrives silently while the preference request is
still in flight. Rendering it into the navbar costs one cached row.
"""
from __future__ import annotations


def alert_preferences(request):
    """Expose the signed-in user's alert preferences as ``alert_prefs``.

    Returns an empty context for anonymous requests and swallows database
    errors: the navbar renders on every page, including error pages and the
    login screen, and a preferences lookup must never be the reason one of them
    fails to render.
    """
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {}

    try:
        from .models import NotificationPreference

        return {"alert_prefs": NotificationPreference.for_user(user)}
    except Exception:
        return {}
