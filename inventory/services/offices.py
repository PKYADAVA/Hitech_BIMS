"""Which branch an office belongs to, and which offices a branch has.

The link is not a column on ``Warehouse`` — it is a row in the generic
``inventory.Mapping`` table under ``sector_branch``, edited from the Office →
Branch master (see inventory.views.warehouse_mapping_data and the linked-tree
screen). Reading it takes knowing that, which is why it lives here rather than
being rediscovered by every report that needs to ask.

An office with no row belongs to no branch. That is a real answer, not a
missing one — Main Warehouse and the hatchery stores are nobody's branch — so
callers get nothing back for it rather than a guess, and are expected to say
so on screen rather than let the money disappear into a filtered total.
"""
from inventory.models import Mapping


def offices_for_branch(branch_id):
    """Ids of the offices mapped to this branch — the locations its money is
    taken at. Empty when the branch has no office mapped to it at all."""
    return offices_for_branches([branch_id] if branch_id else [])


def offices_for_branches(branch_ids):
    """The same for several branches at once — what a user scoped to a handful
    of them may see the money of. Empty for an empty list, which is a real
    answer: a branch with no office of its own takes no money of its own."""
    ids = [b for b in (branch_ids or []) if b]
    if not ids:
        return []
    return list(Mapping.objects.filter(type=Mapping.TYPE_SECTOR_BRANCH,
                                       to_id__in=ids)
                .exclude(to_id=None).values_list("from_id", flat=True))


def branch_of_office(office_id):
    """The branch id an office is mapped to, or None when it is mapped to
    nothing — including when it was explicitly unmapped (``to_id`` null)."""
    if not office_id:
        return None
    row = (Mapping.objects.filter(type=Mapping.TYPE_SECTOR_BRANCH,
                                  from_id=office_id)
           .values_list("to_id", flat=True).first())
    return row or None


def mapped_office_ids():
    """Every office that belongs to some branch. What is left over is what a
    branch-filtered figure cannot account for."""
    return list(Mapping.objects.filter(type=Mapping.TYPE_SECTOR_BRANCH)
                .exclude(to_id=None).values_list("from_id", flat=True))
