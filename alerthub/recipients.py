"""Who a hand-written notification can reach, and who it will.

The Send Notification page narrows people down an organisational cascade —
company, branch, farm, warehouse, department, role — and the picker, the
preview panel and the send itself all have to agree on the answer. They agree
because all three call this module. A second implementation behind the JSON
endpoint is exactly how the number in the preview ends up disagreeing with the
list above it.

**No permissions are defined here.** Two masters already answer the questions
this module needs, and both are read rather than reimplemented:

* :mod:`user.services.scoping` — the Employee Organization Access master. It
  says which companies, branches, farms and warehouses a person is attached to.
  It decides both *which employees match a filter* and *which filters a sender
  may use at all*.
* :mod:`user.access` — the Web-Access matrix. It decides who may open the page,
  and is checked in the view rather than here.

**How an employee belongs to a branch.** Not through a column on
:class:`hr.Employee` — there isn't one — but through
:class:`user.EmployeeAccessProfile`, the master an administrator already fills
in. Reusing it means the picker cannot disagree with the data scope the rest of
the ERP enforces, and nobody maintains the same fact twice.

The consequence worth knowing, and worth saying on the page: an employee with
no access profile has no recorded organisational home, so filtering by branch
does not find them. They are reachable with the hierarchy left open.
"""
from __future__ import annotations

from django.contrib.auth.models import Group
from django.db.models import Q


# ---------------------------------------------------------------------------
# What the *sender* may aim at
# ---------------------------------------------------------------------------

def sender_scope(user):
    """The querysets a sender may choose from, from the existing access master.

    A user attached to Akbarpur must not be able to address Tulsipur's staff.
    That is not a new rule and gets no new table: ``branches_for`` and friends
    are the same helpers the reports and the alert-config master already use,
    so a scope change made in one place moves this page with it.
    """
    from account.models import CompanyProfile
    from hr.models import Department, Designation
    from user.services.scoping import branches_for, farms_for, warehouses_for

    return {
        # CompanyProfile carries no scope column of its own; the employee
        # profile's ``companies`` is the only thing that limits it, and an
        # unscoped user sees the lot.
        "companies": CompanyProfile.objects.order_by("name"),
        "branches": branches_for(user).order_by("branch_name"),
        "farms": farms_for(user).select_related("branch").order_by("farm_name"),
        "warehouses": warehouses_for(user).order_by("name"),
        # Departments, designations and groups are vocabulary, not territory —
        # nothing in the access master restricts them, and restricting them
        # here would be inventing a permission.
        "departments": Department.objects.filter(is_active=True).order_by("name"),
        "designations": Designation.objects.order_by("title"),
        "groups": Group.objects.order_by("name"),
    }


def employee_queryset(sender=None):
    """Every employee this sender could notify at all, before any filtering.

    A login is the thing being notified, so an employee without one is not a
    candidate, and an inactive account is a row nobody will ever read.

    When ``sender`` is given, the pool is cut to their authorised branches and
    farms up front. Doing it here rather than in the view means every caller —
    picker, preview, "Select All", and the save-time revalidation — inherits the
    restriction, so there is no path that quietly skips it.
    """
    from hr.models import Employee

    qs = (
        Employee.objects
        .filter(user__isnull=False, user__is_active=True)
        .select_related("user", "department", "designation", "group",
                        "warehouse", "access_profile")
    )
    if sender is not None:
        from user.services.scoping import is_unscoped

        if not is_unscoped(sender):
            scope = sender_scope(sender)
            branch_ids = list(scope["branches"].values_list("id", flat=True))
            farm_ids = list(scope["farms"].values_list("id", flat=True))
            # An employee with no profile has no recorded home, so a scoped
            # sender cannot establish that they are inside their territory.
            # Leaving them out is the safe answer and the page says so.
            qs = qs.filter(
                Q(access_profile__all_branches=True)
                | Q(access_profile__branches__in=branch_ids)
                | Q(access_profile__farms__in=farm_ids),
                access_profile__is_active=True,
            )
    return qs.order_by("full_name", "user__username").distinct()


# ---------------------------------------------------------------------------
# Narrowing down the hierarchy
# ---------------------------------------------------------------------------

def filter_employees(qs=None, *, sender=None, companies=None, branches=None,
                     farms=None, warehouses=None, departments=None,
                     designations=None):
    """Narrow the candidates down the cascade. Any level may be left open.

    Each argument is a list; an empty or missing one adds no clause, so "All
    Branches" is not a special case — it is simply the absence of a filter.
    Levels combine with AND (a branch *and* a department), values within a level
    with OR (either of two branches), which is how the page reads top to bottom.
    """
    qs = employee_queryset(sender) if qs is None else qs

    companies = _ids(companies)
    branches = _ids(branches)
    farms = _ids(farms)
    warehouses = _ids(warehouses)
    departments = _ids(departments)
    designations = _ids(designations)

    if companies:
        qs = qs.filter(
            Q(access_profile__all_companies=True)
            | Q(access_profile__companies__in=companies),
            access_profile__is_active=True,
        )

    if branches:
        # "All branches" on a profile genuinely covers this one, so those
        # employees match too — that is what the flag means in scoping.py, and
        # answering differently here would make the picker contradict the
        # access master it reads from.
        qs = qs.filter(
            Q(access_profile__all_branches=True)
            | Q(access_profile__branches__in=branches),
            access_profile__is_active=True,
        )

    if farms:
        # Farms cascade from branches: an unrestricted farm scope means all
        # farms *of the branches in scope*, which the branch clause above has
        # already established. See EmployeeAccessProfile.all_farms.
        qs = qs.filter(
            Q(access_profile__all_farms=True)
            | Q(access_profile__farms__in=farms),
            access_profile__is_active=True,
        )

    if warehouses:
        # Two records place a person at a store: the HR posting
        # (Employee.warehouse) and the access profile. Either counts — a send
        # that missed the feed-store clerk because only one was filled in would
        # be a silent failure.
        qs = qs.filter(
            Q(warehouse_id__in=warehouses)
            | Q(access_profile__all_warehouses=True,
                access_profile__is_active=True)
            | Q(access_profile__warehouses__in=warehouses,
                access_profile__is_active=True)
        )

    if departments:
        qs = qs.filter(department_id__in=departments)

    if designations:
        qs = qs.filter(designation_id__in=designations)

    return qs.distinct()


def warehouses_for_branches(user, branch_ids=None):
    """Warehouses of the chosen branches, within the sender's own scope.

    Warehouse carries no branch column — that fact lives in the Office Mapping
    master (``inventory.Mapping``, sector → branch), which is where
    ``EmployeeAccessProfile`` reads it from too.
    """
    from inventory.models import Mapping
    from user.services.scoping import warehouses_for

    qs = warehouses_for(user).order_by("name")
    branch_ids = _ids(branch_ids)
    if not branch_ids:
        return qs
    mapped = Mapping.objects.filter(
        type=Mapping.TYPE_SECTOR_BRANCH, to_id__in=branch_ids
    ).values_list("from_id", flat=True)
    return qs.filter(pk__in=list(mapped))


def farms_for_branches(user, branch_ids=None):
    """Farms of the chosen branches, within the sender's own scope."""
    from user.services.scoping import farms_for

    qs = farms_for(user).select_related("branch").order_by("farm_name")
    branch_ids = _ids(branch_ids)
    return qs.filter(branch_id__in=branch_ids) if branch_ids else qs


# ---------------------------------------------------------------------------
# What the page renders
# ---------------------------------------------------------------------------

def employee_options(**filters):
    """The picker's list: ``[{id, name, code, role, department, initials}, …]``.

    ``id`` is the **user** id, not the employee id — the notification is
    addressed to a login, and carrying the employee id here would mean
    translating it back on save and getting it wrong once.
    """
    rows, seen = [], set()
    for emp in filter_employees(**filters):
        # A bad data set can point two employee rows at one login; the picker
        # must not then offer the same person twice.
        if emp.user_id in seen:
            continue
        seen.add(emp.user_id)
        name = ((emp.full_name or "").strip()
                or emp.user.get_full_name().strip()
                or emp.user.username)
        rows.append({
            "id": emp.user_id,
            "name": name,
            "code": str(emp.employee_id or ""),
            "role": str(emp.designation) if emp.designation_id else "",
            "department": emp.department.name if emp.department_id else "",
            "initials": initials(name),
        })
    return rows


def group_options():
    """Groups offered as whole-team recipients, with their live member counts."""
    return [
        {"id": g.pk, "name": g.name,
         "members": g.user_set.filter(is_active=True).count()}
        for g in Group.objects.order_by("name")
    ]


def delivery_preview(*, user_ids=None, group_ids=None):
    """Exactly what the Recipient Preview panel promises, computed once.

    ``total`` is the **de-duplicated union**. Someone selected through a branch,
    a role and by name is one recipient, not three — "each recipient will
    receive this only once" is a claim this function has to make true, and the
    send calls the same helper so the promise and the delivery cannot drift.

    Inactive accounts are reported separately rather than silently dropped. A
    count that quietly shrinks between the preview and the send is the failure
    this returns ``excluded`` to prevent.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user_ids = set(_ids(user_ids))
    group_ids = list(_ids(group_ids))

    reached = set(user_ids)
    if group_ids:
        reached |= set(
            User.objects.filter(groups__in=group_ids).values_list("id", flat=True)
        )

    excluded = list(
        User.objects.filter(pk__in=reached, is_active=False)
        .values_list("id", "username", "first_name", "last_name")
    )
    excluded_names = [
        (f"{first} {last}".strip() or username)
        for _pk, username, first, last in excluded
    ]

    active_ids = reached - {row[0] for row in excluded}
    return {
        "total": len(active_ids),
        "employees": len(user_ids),
        "groups": len(group_ids),
        "excluded": len(excluded),
        "excluded_names": excluded_names,
        "push_capable": _push_capable(active_ids),
    }


def _push_capable(user_ids) -> int:
    """How many of these people have the app installed and push left on.

    Reported rather than assumed: "12 mobile app users" on the delivery preview
    has to be a fact about registered devices, not a guess from headcount.
    """
    if not user_ids:
        return 0
    from notification.models import DeviceToken

    from .models import NotificationPreference

    with_devices = set(
        DeviceToken.objects.filter(user_id__in=user_ids)
        .values_list("user_id", flat=True)
    )
    opted_out = set(
        NotificationPreference.objects
        .filter(user_id__in=with_devices, receive_push=False)
        .values_list("user_id", flat=True)
    )
    return len(with_devices - opted_out)


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _ids(value):
    """Model instances, ids or a queryset — all reduced to a list of ints."""
    if not value:
        return []
    out = []
    for item in value:
        pk = getattr(item, "pk", item)
        try:
            out.append(int(pk))
        except (TypeError, ValueError):
            continue
    return out
