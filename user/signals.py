"""Keep the Mobile Access cache honest.

The cache holds one answer per user, so it has to be retired whenever any of
its three inputs move: the module switches, the screen matrix, or which groups
the user belongs to. Membership is the one that is easy to forget — it is
changed from four places (the web editor, the mobile API, Django admin, and a
shell) and none of them is where the cache lives, so it is caught by signal
rather than by remembering.

An access cache that serves a stale "yes" is a security bug, not a performance
one, which is why invalidation is wired to the model rather than to the views
that happen to write it today.
"""
from django.contrib.auth.models import User
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .models import GroupMobileAccess, GroupMobileTabPermission


def _invalidate(**_kwargs):
    from .services.mobile_access import invalidate

    invalidate()


for model in (GroupMobileAccess, GroupMobileTabPermission):
    post_save.connect(_invalidate, sender=model,
                      dispatch_uid=f"mobile_access_cache_save_{model.__name__}")
    post_delete.connect(_invalidate, sender=model,
                        dispatch_uid=f"mobile_access_cache_delete_{model.__name__}")


@receiver(m2m_changed, sender=User.groups.through,
          dispatch_uid="mobile_access_cache_groups")
def _groups_changed(action, **_kwargs):
    # Only the actions that change membership; pre_* fire before the write and
    # would cache the old answer back in if anything read during them.
    if action in {"post_add", "post_remove", "post_clear"}:
        _invalidate()
