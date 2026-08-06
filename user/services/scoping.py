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

#: The same dimensions on an employee profile, which names two of them
#: differently — "sectors" is the group profile's word for warehouses.
EMPLOYEE_SCOPES = {
    "branches": ("all_branches", "branches"),
    "farms": ("all_farms", "farms"),
    "sectors": ("all_warehouses", "warehouses"),
}


def employee_profile_for(user):
    """The active organizational access profile for this login, or None.

    Reached through the employee's user link, which is also what decides whose
    trip a supervisor is logging — one relationship, not a second one to keep
    in step.
    """
    from user.models import EmployeeAccessProfile

    if not user or not getattr(user, "is_authenticated", False):
        return None
    return (EmployeeAccessProfile.objects
            .filter(employee__user=user, is_active=True)
            .prefetch_related("branches", "farms", "warehouses")
            .first())


def _employee_allowed_ids(profile, scope):
    """What one employee profile permits for ``scope``, or None for no limit.

    Two dimensions cascade rather than standing alone. "All farms" means all
    farms *of the branches in scope*, and warehouses likewise — that is what
    makes the page usable: pick two branches and everything beneath them
    follows without listing any of it. Only when branches are unrestricted too
    does "all" mean every row in the table.
    """
    if scope not in EMPLOYEE_SCOPES:
        # A dimension this page does not cover — lines, customer and supplier
        # groups. The profile replaces the group scope, and it says nothing
        # about these, so they are unrestricted rather than empty.
        return None

    all_flag, field = EMPLOYEE_SCOPES[scope]
    if not getattr(profile, all_flag):
        return set(getattr(profile, field).values_list("id", flat=True))

    branch_ids = (None if profile.all_branches
                  else set(profile.branches.values_list("id", flat=True)))
    if scope == "branches" or branch_ids is None:
        return None

    if scope == "farms":
        from broiler.models import BroilerFarm
        return set(BroilerFarm.objects.filter(branch_id__in=branch_ids)
                   .values_list("id", flat=True))

    # Warehouses reach their branch through the Office Mapping master rather
    # than a column of their own — see EmployeeAccessProfile.all_warehouses.
    from inventory.models import Mapping
    return set(Mapping.objects
               .filter(type=Mapping.TYPE_SECTOR_BRANCH, to_id__in=branch_ids)
               .values_list("from_id", flat=True))


def is_unscoped(user):
    """True when no scoping applies at all — superuser, Admin group, or a user
    with neither an employee profile nor a group carrying one."""
    from user.access import _user_is_unrestricted
    from user.models import GroupAccessProfile

    if not user or not user.is_authenticated:
        return True
    if _user_is_unrestricted(user):
        return True
    if employee_profile_for(user) is not None:
        return False
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

    # An employee's own profile replaces the group scope rather than narrowing
    # or widening it. Two people can share a role and not a territory, and no
    # arrangement of groups says that without inventing a group per person —
    # so where an administrator has answered for the person, that is the
    # answer. Groups still decide which tabs and which actions.
    profile = employee_profile_for(user)
    if profile is not None:
        return _employee_allowed_ids(profile, scope)

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


def scope_any(user, qs, **scope_fields):
    """Keep a row when *any* named field is in scope, or when all of them are
    empty.

    Transfers have two ends. Requiring both to be in scope would hide a transfer
    out of the user's own warehouse to somewhere else — which is exactly the
    movement they most need to see, and hiding it would make their own store's
    ledger wrong rather than restricted. So one end in scope is enough.

    ``scope_multi`` is the opposite and remains right for single-location rows,
    where each dimension is a separate restriction.
    """
    # One allowed_ids call per dimension, applied to each of its fields.
    limits = {}
    for scope, fields in scope_fields.items():
        ids = allowed_ids(user, scope)
        if ids is None:
            continue                       # this dimension is unrestricted
        for field in _as_list(fields):
            limits[field] = ids
    if not limits:
        return qs

    match = Q()
    empty = Q()
    for field, ids in limits.items():
        match |= Q(**{f"{field}__in": ids})
        empty &= Q(**{f"{field}__isnull": True})
    return qs.filter(match | empty).distinct()


def _as_list(value):
    return [value] if isinstance(value, str) else list(value)


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


def farm_ids_for(user):
    """Allowed farm ids, or ``None`` when the user is not limited to any.

    ``farms_for`` narrows by the farm scope *and* by the branch scope, so this
    cannot be read off ``allowed_ids(user, "farms")`` alone — a user limited
    only by branch has no explicit farm list but still may not see every farm.
    The ``None`` is what keeps "no limit" distinct from "a limit that happens
    to permit nothing".
    """
    if is_unscoped(user):
        return None
    if allowed_ids(user, "farms") is None and allowed_ids(user, "branches") is None:
        return None
    return set(farms_for(user).values_list("id", flat=True))


def lines_for(user, qs=None):
    from broiler.models import BroilerLine
    return scope_queryset(user, qs if qs is not None else BroilerLine.objects.all(),
                          "lines")


def supervisors_for(user, qs=None):
    """Supervisors belong to a branch, so the branch scope carries them."""
    from broiler.models import Supervisor

    qs = qs if qs is not None else Supervisor.objects.all()
    return scope_queryset(user, qs, "branches", "branch_id")


def customers_for(user, qs=None):
    """Customers, narrowed by the customer-group scope."""
    from sales.models import Customer

    qs = qs if qs is not None else Customer.objects.all()
    return scope_or_null(user, qs, "customer_groups", "customer_group_id")


def suppliers_for(user, qs=None):
    """Suppliers, narrowed by the supplier-group scope.

    ``Supplier.supplier_group`` is free text while the scope holds VendorGroup
    rows, so the allowed groups are resolved to their descriptions and matched
    on that. A supplier with no group set is kept: an unfiled record is not
    evidence that this user should be denied it, and dropping such rows would
    change balance totals rather than restrict access.
    """
    from purchase.models import Supplier, VendorGroup

    qs = qs if qs is not None else Supplier.objects.all()
    ids = allowed_ids(user, "supplier_groups")
    if ids is None:
        return qs
    names = list(VendorGroup.objects.filter(id__in=ids)
                 .values_list("description", flat=True))
    return qs.filter(Q(supplier_group__in=names)
                     | Q(supplier_group__isnull=True)
                     | Q(supplier_group=""))


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
