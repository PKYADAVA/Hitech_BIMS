"""Template helpers for the signed-in user.

Kept in the user app because that is whose data they read; the navbar is only
the first thing to want them.
"""
from django import template

register = template.Library()


@register.filter
def initials(user):
    """One or two letters standing for a person, for the navbar avatar.

    First and last name where the account carries them, because that is what a
    colleague would recognise. Falling back to the username, which many of
    these accounts are all they have: two letters of it read as a name, one
    letter reads as an error.

    Never empty — a blank avatar looks like a page that failed to load rather
    than an account with no name on it.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return "?"

    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    if first and last:
        return (first[0] + last[0]).upper()
    if first:
        return first[:2].upper()

    name = (getattr(user, "username", "") or "").strip()
    if not name:
        return "?"
    # A username of two words is a name written the long way round.
    parts = [p for p in name.replace(".", " ").replace("_", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


@register.filter
def display_name(user):
    """The fullest name the account has, for a tooltip or a menu heading."""
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    full = " ".join(p for p in ((getattr(user, "first_name", "") or "").strip(),
                                (getattr(user, "last_name", "") or "").strip()) if p)
    return full or (getattr(user, "username", "") or "")
