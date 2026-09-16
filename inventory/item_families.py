"""Which items count as feed, which as chicks, and which as medicine.

These answers decide what a form may offer, what a register may list, and
which of a batch report's tables a movement belongs in; they were written out
by hand thirteen times before being collected into one place. They live here
rather than in broiler/views.py — where they were first needed — because both
apps ask the question now: Broiler asks it of a Daily Entry's feed columns,
Inventory asks it of a stock transfer, and the two have to agree or the same
movement is a placement on one screen and not on the other.

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


def medicine_items():
    """Everything else a flock receives — medicine, vaccine, health products.

    The one family without a name to match on: a site calls the category
    "Medicine", "Vaccine", "Medicine & Vaccine" or its own house name, and
    there is nothing common to match. So it is defined by exclusion — what a
    farm is sent that is neither feed nor chicks — which is what the Batch
    History Report's Medicine and Vaccine tables have always meant.
    """
    from .models import Item

    return (Item.objects
            .exclude(category__name__icontains="feed")
            .exclude(category__name__icontains="chick")
            .order_by("item_code"))


def item_family(item):
    """Which family one item belongs to: "chicks", "feed" or "medicine".

    The same three rules as the querysets above, asked of an item already in
    hand — a report walking transfer rows would otherwise run a query per row
    to ask the question the category name answers on its own.
    """
    name = (item.category.name if item.category_id else "").lower()
    if "chick" in name:
        return "chicks"
    if "feed" in name:
        return "feed"
    return "medicine"


#: Family name -> the items in it. What a caller may pass as ?item_family=.
ITEM_FAMILIES = {
    "chicks": chick_items,
    "feed": feed_items,
    "medicine": medicine_items,
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
