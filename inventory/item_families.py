"""Which items count as feed, and which as chicks.

These two answers decide what a form may offer and what a register may list,
and they were written out by hand thirteen times before being collected into
one place. They live here rather than in broiler/views.py — where they were
first needed — because both apps ask the question now: Broiler asks it of a
Daily Entry's feed columns, Inventory asks it of a stock transfer, and the two
have to agree or the same movement is a placement on one screen and not on the
other.

Matched on the category's *name* rather than an id: the category is created by
whoever sets up Inventory, so there is no fixed id to hold on to, and a site
running both "Broiler Feed" and "Pre-Starter Feed" wants both.
"""


def feed_items():
    """The items a Daily Entry may record as feed."""
    from .models import Item

    return Item.objects.filter(category__name__icontains="feed").order_by("item_code")


def chick_items():
    """The items a placement may move onto a farm — the same rule, for chicks."""
    from .models import Item

    return Item.objects.filter(category__name__icontains="chick").order_by("item_code")


#: Family name -> the items in it. What a caller may pass as ?item_family=.
ITEM_FAMILIES = {
    "chicks": chick_items,
    "feed": feed_items,
}


def filter_by_item_family(queryset, family, field="item"):
    """Narrow a queryset of item-bearing rows to one family.

    An unknown family narrows to nothing rather than being ignored. A filter
    that silently does not apply is how the Chicks Placement register came to
    list feed dispatches: the caller asked for chicks, was given everything,
    and nothing said so.
    """
    items = ITEM_FAMILIES.get(family)
    if items is None:
        return queryset.none()
    return queryset.filter(**{f"{field}__in": items().values("id")})
