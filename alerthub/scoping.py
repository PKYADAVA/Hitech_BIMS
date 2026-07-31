"""Who may see which alert — the security boundary of this module.

Two independent gates, and a notification has to pass **both**:

1. **Targeting.** You were sent it. There is a
   :class:`~alerthub.models.NotificationRecipient` row joining you to it.
2. **Scope.** You may still see it *now*. Every scope column on the
   notification is re-checked against your current Branch / Organization
   Centre / Farm / Warehouse access on every read.

The second gate is not redundant. Targeting is decided once, when the alert is
raised; access changes afterwards. Someone moved off the Akbarpur branch keeps
their recipient rows, and without the re-check would go on reading Akbarpur's
mortality alerts indefinitely. Re-filtering on read costs one indexed lookup and
makes revocation immediate, which is what "never show alerts belonging to
another branch" has to mean.

**Null scope columns are visible.** A system alert has no branch, and a stock
alert has no farm. An empty column means "this alert is not about a branch",
not "this alert is about a branch you lack" — so it passes, exactly as
:func:`user.services.scoping.scope_or_null` treats optional links elsewhere in
this codebase. Targeting still decides who was told; scope only ever takes away.

Everything here delegates to :mod:`user.services.scoping` so this module can
never drift from the Web-Access matrix that governs the rest of the ERP.
"""
from __future__ import annotations

from django.db.models import Q

from user.services.scoping import allowed_ids, is_unscoped

#: notification field -> the GroupAccessProfile scope that governs it.
#: ``org_centre`` is absent by design: GroupAccessProfile has no organization
#: centre dimension, so it is derived from the branch scope in
#: :func:`_org_centre_limit` rather than invented here.
SCOPE_FIELDS = {
    "branch_id": "branches",
    "farm_id": "farms",
    "warehouse_id": "sectors",
}


def _org_centre_limit(user):
    """Organization-centre ids this user may see, or None for no limit.

    There is no org-centre scope on ``GroupAccessProfile``, but every centre
    that represents a branch is linked to one (``OrganizationCentre.branch``,
    populated by ``account.signals.branch_cost_center``). So a branch-scoped
    user is scoped to those branches' centres, plus every centre that is not a
    branch at all — a Vehicle or Department centre is not another branch's data
    and withholding it would hide finance alerts from everyone with a branch
    limit.
    """
    branch_ids = allowed_ids(user, "branches")
    if branch_ids is None:
        return None

    from account.models import OrganizationCentre

    return set(
        OrganizationCentre.objects.filter(
            Q(branch_id__in=branch_ids) | Q(branch__isnull=True)
        ).values_list("id", flat=True)
    )


def scope_filter(user) -> Q:
    """The scope half of visibility, as a ``Q`` for reuse in other queries."""
    if is_unscoped(user):
        return Q()

    condition = Q()
    for field, scope in SCOPE_FIELDS.items():
        ids = allowed_ids(user, scope)
        if ids is None:
            continue
        condition &= Q(**{f"{field}__in": ids}) | Q(**{f"{field}__isnull": True})

    centre_ids = _org_centre_limit(user)
    if centre_ids is not None:
        condition &= Q(org_centre_id__in=centre_ids) | Q(org_centre__isnull=True)
    return condition


def visible_notifications(queryset, user):
    """Restrict ``queryset`` to notifications ``user`` is entitled to read.

    Targeting *and* scope. Anonymous users get nothing — there is no public
    alert, and returning the unfiltered queryset on a missing user is the
    classic way these functions fail open.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()

    # Targeting. distinct() because the join to recipients can duplicate rows
    # once other filters widen the query.
    queryset = queryset.filter(recipients__user=user).distinct()
    return queryset.filter(scope_filter(user))


def can_see(user, notification) -> bool:
    """Whether one user may read one notification. Used by the detail view."""
    from .models import Notification

    return (
        visible_notifications(Notification.objects.filter(pk=notification.pk), user)
        .exists()
    )


# ---------------------------------------------------------------------------
# Fan-out: who gets told when an alert is raised
# ---------------------------------------------------------------------------

def audience_for(rule, notification):
    """Users who should receive ``notification`` under ``rule``.

    Three filters, narrowing in order:

    * **Groups.** The rule's ``notify_groups``, or every active user when it
      names none.
    * **Scope.** Each candidate must pass the same scope check they would face
      on read. Skipping this would create recipient rows that the read path then
      hides — an alert nobody can open, and a badge count that never clears.
    * **Preference.** A user who switched in-app alerts off, or set a minimum
      priority above this one, is not a recipient.

    Inactive users are excluded throughout: fanning out to a disabled account
    writes rows nobody will ever read.
    """
    from django.contrib.auth import get_user_model

    from .constants import PRIORITY_RANK
    from .models import NotificationPreference

    User = get_user_model()
    candidates = User.objects.filter(is_active=True)

    group_ids = list(rule.notify_groups.values_list("id", flat=True))
    if group_ids:
        candidates = candidates.filter(groups__id__in=group_ids).distinct()

    # Preferences are read in one query rather than per user; absent rows mean
    # defaults, which allow in-app at every priority.
    prefs = {
        pref.user_id: pref
        for pref in NotificationPreference.objects.filter(
            user__in=candidates,
        )
    }
    alert_rank = PRIORITY_RANK.get(notification.priority, 99)

    recipients = []
    for user in candidates.prefetch_related("groups"):
        if not _in_scope(user, notification):
            continue
        pref = prefs.get(user.id)
        if pref is not None:
            if not pref.receive_in_app:
                continue
            if alert_rank > PRIORITY_RANK.get(pref.min_priority, 99):
                continue
        recipients.append(user)
    return recipients


def _in_scope(user, notification) -> bool:
    """Whether ``notification``'s scope columns fall inside ``user``'s access.

    Evaluated in Python rather than SQL because the fan-out already holds the
    notification in memory and would otherwise run one query per candidate user.
    The rules are the same ones :func:`scope_filter` expresses; keep the two in
    step.
    """
    if is_unscoped(user):
        return True

    pairs = (
        (notification.branch_id, "branches"),
        (notification.farm_id, "farms"),
        (notification.warehouse_id, "sectors"),
    )
    for value, scope in pairs:
        if value is None:
            continue                      # not about that dimension
        ids = allowed_ids(user, scope)
        if ids is not None and value not in ids:
            return False

    if notification.org_centre_id is not None:
        centre_ids = _org_centre_limit(user)
        if centre_ids is not None and notification.org_centre_id not in centre_ids:
            return False
    return True


def rule_applies_to(rule, *, branch=None, org_centre=None, farm=None,
                    warehouse=None) -> bool:
    """Whether a rule's notify-targets permit raising an alert for this subject.

    The ``notify_*`` collections on :class:`~alerthub.models.AlertRule` narrow
    *what the rule watches*, not who hears about it — "High mortality, but only
    for the Akbarpur farms". Who hears about it is :func:`audience_for`.

    An empty collection means no restriction on that dimension. A subject with
    no value for a dimension the rule restricts is **not** excluded: a rule
    limited to two farms should still fire on a warehouse-level subject it
    happens to match on every other dimension, and silently dropping those made
    rules look broken.
    """
    checks = (
        (rule.notify_branches, branch),
        (rule.notify_org_centres, org_centre),
        (rule.notify_farms, farm),
        (rule.notify_warehouses, warehouse),
    )
    for manager, value in checks:
        if value is None:
            continue
        allowed = set(manager.values_list("id", flat=True))
        if allowed and _pk(value) not in allowed:
            return False
    return True


def _pk(value):
    return value if isinstance(value, int) else getattr(value, "pk", None)
