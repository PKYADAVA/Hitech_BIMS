"""Data scoping — the second half of the Web-Access matrix.

``GroupAccessProfile`` has always stored which branches, lines, farms, sectors
(warehouses) and customer/supplier groups a group is limited to. Nothing read
it: the editor implied a restriction the server never applied, so a user scoped
to one branch still saw every branch in every dropdown and every report. This
module is what reads it.

Two rules govern how it combines, both matching the tab matrix so the two halves
of the permission system behave the same way:

* **Granted anywhere is granted.** A user in several groups gets the union of
  their scopes, and one group with "All" makes that dimension unrestricted.
* **Unconfigured means unrestricted.** A user with no groups, or whose groups
  have no access profile, is not scoped — the same fail-open the tab matrix
  uses, so adding this cannot lock out an existing account.

Superusers and Admin access-type groups bypass, as everywhere else.

``None`` from any of the ``allowed_*`` helpers means "no limit". An empty set
means a real limit that happens to permit nothing, which is not the same thing
and must not be collapsed into it.
"""
from django.db.models import Q

#: profile field -> (all-flag, m2m) for each scoped dimension.
SCOPES = {
    "branches": ("all_branches", "branches"),
    "lines": ("all_lines", "lines"),
    "farms": ("all_farms", "farms"),
    "sectors": ("all_sectors", "sectors"),
    "customer_groups": ("all_customer_groups", "customer_groups"),
    "supplier_groups": ("all_supplier_groups", "supplier_groups"),
}


def is_unscoped(user):
    """True when no scoping applies at all — superuser, Admin group, or a user
    whose groups carry no access profile."""
    from user.access import _user_is_unrestricted
    from user.models import GroupAccessProfile

    if not user or not user.is_authenticated:
        return True
    if _user_is_unrestricted(user):
        return True
    return not GroupAccessProfile.objects.filter(group__in=user.groups.all()).exists()


def allowed_ids(user, scope):
    """Ids of ``scope`` this user may see, or ``None`` for no limit.

    An empty set is a real answer: a group that ticked "not all" and then chose
    nothing permits nothing. Returning None there would silently hand over
    everything, which is the failure this module exists to fix.
    """
    from user.models import GroupAccessProfile

    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}")
    if is_unscoped(user):
        return None

    all_flag, field = SCOPES[scope]
    profiles = GroupAccessProfile.objects.filter(group__in=user.groups.all())

    ids = set()
    for profile in profiles:
        if getattr(profile, all_flag):
            return None                      # one group with "All" opens it up
        ids.update(getattr(profile, field).values_list("id", flat=True))
    return ids


def scope_queryset(user, qs, scope, field="id"):
    """Narrow ``qs`` to what ``user`` may see for ``scope``.

    ``field`` is the path from the queryset's model to the scoped object, so the
    same call filters a list of branches (``id``) and a list of farms by their
    branch (``branch_id``).
    """
    ids = allowed_ids(user, scope)
    if ids is None:
        return qs
    return qs.filter(**{f"{field}__in": ids})


def scope_multi(user, qs, **scope_fields):
    """Apply several scopes to one queryset: ``scope_multi(u, qs,
    branches="branch_id", sectors="warehouse_id")``.

    Every named scope must pass — a row has to be inside all of them — because
    each dimension is a separate restriction rather than an alternative.
    """
    for scope, field in scope_fields.items():
        qs = scope_queryset(user, qs, scope, field)
    return qs


def scope_or_null(user, qs, scope, field):
    """Like :func:`scope_queryset` but keeps rows where the field is empty.

    For optional links — a stock transfer with no branch is not evidence that
    the user should be denied it, and dropping such rows would quietly change
    report totals rather than restrict access.
    """
    ids = allowed_ids(user, scope)
    if ids is None:
        return qs
    return qs.filter(Q(**{f"{field}__in": ids}) | Q(**{f"{field}__isnull": True}))


# ---------------------------------------------------------------------------
# The option lists people actually see
# ---------------------------------------------------------------------------

def branches_for(user, qs=None):
    from broiler.models import Branch
    return scope_queryset(user, qs if qs is not None else Branch.objects.all(),
                          "branches")


def farms_for(user, qs=None):
    """Farms, narrowed by the farm scope *and* by the branch scope.

    A user limited to Akbarpur branch should not see another branch's farms even
    if nobody listed farms explicitly — the branch limit already implies it.
    """
    from broiler.models import BroilerFarm

    qs = qs if qs is not None else BroilerFarm.objects.all()
    qs = scope_queryset(user, qs, "farms")
    return scope_queryset(user, qs, "branches", "branch_id")


def warehouses_for(user, qs=None):
    from inventory.models import Warehouse
    return scope_queryset(user, qs if qs is not None else Warehouse.objects.all(),
                          "sectors")


def lines_for(user, qs=None):
    from broiler.models import BroilerLine
    return scope_queryset(user, qs if qs is not None else BroilerLine.objects.all(),
                          "lines")


def supervisors_for(user, qs=None):
    """Supervisors belong to a branch, so the branch scope carries them."""
    from broiler.models import Supervisor

    qs = qs if qs is not None else Supervisor.objects.all()
    return scope_queryset(user, qs, "branches", "branch_id")


def describe(user):
    """Human summary of a user's scope, for showing on a scoped page."""
    labels = {"branches": "branch", "lines": "line", "farms": "farm",
              "sectors": "warehouse", "customer_groups": "customer group",
              "supplier_groups": "supplier group"}
    if is_unscoped(user):
        return ""
    parts = []
    for scope, label in labels.items():
        ids = allowed_ids(user, scope)
        if ids is not None:
            parts.append(f"{len(ids)} {label}{'' if len(ids) == 1 else 's'}")
    return ", ".join(parts)
