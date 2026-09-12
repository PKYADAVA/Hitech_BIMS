"""Branch / Warehouse filtering for the transaction list pages.

The Broiler > Transactions lists filtered by date alone, so finding one
branch's entries in a busy month meant reading past every other branch's.

Here rather than in either app because the pages and their APIs do not live
together: Chicks Placement is a Broiler page served by ``inventory``'s
StockTransfer API, and inventory already imports from broiler — importing back
the other way would close a cycle.

What a page can offer is decided by what its own record carries, not by a wish
for symmetry. A daily entry knows its farm and reaches a branch through it; a
receipt knows the warehouse it was taken at and no branch at all, because
Warehouse has none. A control that cannot filter anything is worse than no
control, so each page is given only what it can answer.
"""
from __future__ import annotations


def place_filter_options(user, *, branches: bool = True, warehouses: bool = False) -> dict:
    """Scoped Branch / Warehouse options for a list page's filter bar.

    Scoped, because the options a filter offers must not be wider than the
    rows behind it — otherwise the bar invites a question the grid will answer
    with silence.
    """
    from broiler.models import Branch
    from inventory.models import Warehouse
    from user.services.scoping import branches_for, warehouses_for

    context = {}
    if branches:
        context["filter_branches"] = branches_for(
            user, Branch.objects.order_by("branch_name"))
    if warehouses:
        context["filter_warehouses"] = warehouses_for(
            user, Warehouse.objects.order_by("name"))
    return context


def apply_place_filters(request, qs, *, branch=None, warehouse=None):
    """Apply the ``?branch=`` / ``?warehouse=`` the filter bar sends.

    The lookup paths belong to the caller, which knows its own model; this
    guesses nothing. A path left None means the page offers no such control,
    so that parameter is ignored rather than quietly matching no rows.

    ``warehouse`` accepts several paths: a transfer has two ends, and "at this
    warehouse" means either of them — a placement out of a store is as much
    that store's row as one into it.
    """
    from django.db.models import Q

    chosen_branch = (request.GET.get("branch") or "").strip()
    chosen_warehouse = (request.GET.get("warehouse") or "").strip()

    if chosen_branch and branch:
        qs = qs.filter(**{f"{branch}_id": chosen_branch})
    if chosen_warehouse and warehouse:
        paths = warehouse if isinstance(warehouse, (list, tuple)) else [warehouse]
        match = Q()
        for path in paths:
            match |= Q(**{f"{path}_id": chosen_warehouse})
        qs = qs.filter(match)
    return qs
