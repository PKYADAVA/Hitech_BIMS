"""Global search — one box on the dashboard that reaches the whole ERP.

Two kinds of hit come back:

* **Pages** — every tab in :data:`user.access.MODULE_REGISTRY`, matched on its
  own label *and* on the module and section it sits under, so "purchase report"
  finds the Purchase reports and "chart" finds Chart of Accounts.
* **Records** — the master data people actually search by name: suppliers,
  customers, items, farmers, farms, batches, employees, ledgers and offices.

Every hit is filtered through the Web-Access matrix. A record is only returned
when the user may view the tab that owns it, so search can never surface a
supplier to someone with no access to Purchase. That is the whole reason the
sources below are keyed by tab code rather than by model: the permission answer
already exists, and search reuses it instead of inventing a second one.

Record hits link to their tab's list page carrying ``?find=<term>``, which
main.js feeds into that page's DataTable so the row is filtered to the top on
arrival.
"""
from collections import namedtuple
from importlib import import_module
from urllib.parse import quote

from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from user.access import MODULE_REGISTRY, allowed_view_tabs

# The querystring key a record hit uses to pre-filter the page it lands on.
# Deliberately not "q": report views already read a variety of filter params,
# and "find" collides with none of them.
FIND_PARAM = "find"

PAGE_LIMIT = 8          # pages shown before "…and N more"
PER_SOURCE_LIMIT = 5    # rows read from any one model
RECORD_LIMIT = 15       # records shown across all models

# nav key -> (icon, colour class) for the result list.
NAV_ICONS = {
    "broiler": ("fa-solid fa-egg", "gs-blue"),
    "hatchery": ("fa-solid fa-kiwi-bird", "gs-purple"),
    "purchase": ("fa-solid fa-cart-shopping", "gs-orange"),
    "sales": ("fa-solid fa-indian-rupee-sign", "gs-green"),
    "inventory": ("fa-solid fa-boxes-stacked", "gs-red"),
    "account": ("fa-solid fa-book", "gs-cyan"),
    "hr": ("fa-solid fa-users", "gs-cyan"),
    "user_management": ("fa-solid fa-user-shield", "gs-purple"),
    "notification": ("fa-solid fa-bell", "gs-orange"),
}
DEFAULT_ICON = ("fa-solid fa-file-lines", "gs-blue")

# tab code -> the navbar module it lives under, so a record hit borrows its
# module's icon without each source having to repeat it.
_TAB_NAV = {}
for _module in MODULE_REGISTRY:
    for _section in _module["sections"]:
        for _tab in _section["tabs"]:
            _TAB_NAV.setdefault(_tab[0], _module["nav"])


#: A searchable model.
#:
#: ``tab`` is both the permission gate and the URL the hit links to; ``fields``
#: are searched with icontains; ``title`` / ``subtitle`` are attribute names
#: read off the instance for display (the first non-empty one wins).
RecordSource = namedtuple(
    "RecordSource", "tab kind model_path fields title subtitle")

RECORD_SOURCES = [
    RecordSource("supplier", "Supplier", "purchase.models.Supplier",
                 ["name", "code", "mobile", "gstin", "place"],
                 ["name"], ["code", "place"]),
    RecordSource("customer", "Customer", "sales.models.Customer",
                 ["name", "code", "mobile", "phone", "gstin", "place"],
                 ["name"], ["code", "place"]),
    RecordSource("items", "Item", "inventory.models.Item",
                 ["description", "item_code", "hsn_code"],
                 ["description"], ["item_code"]),
    RecordSource("branch_farm", "Farmer", "broiler.models.Farmer",
                 ["farmer_name", "mobile_no", "phone_no", "aadhar_no", "usc"],
                 ["farmer_name"], ["usc", "mobile_no"]),
    RecordSource("branch_farm", "Farm", "broiler.models.BroilerFarm",
                 ["farm_name", "farm_code", "farm_address", "district", "area"],
                 ["farm_name"], ["farm_code", "district"]),
    RecordSource("broiler_batch", "Batch", "broiler.models.BroilerBatch",
                 ["batch_name", "lot_no", "book_number"],
                 ["batch_name"], ["lot_no"]),
    RecordSource("employee_list", "Employee", "hr.models.Employee",
                 ["full_name", "employee_id", "personal_contact"],
                 ["full_name"], ["employee_id"]),
    RecordSource("coa", "Ledger", "account.models.ChartOfAccount",
                 ["description", "code"],
                 ["description"], ["code"]),
    RecordSource("warehouse", "Office", "inventory.models.Warehouse",
                 ["name", "code", "location"],
                 ["name"], ["code", "location"]),
]


def _load(path):
    module_path, _, attr = path.rpartition(".")
    return getattr(import_module(module_path), attr)


def _terms(query):
    """Query split into words; every word must match somewhere."""
    return [t for t in (query or "").split() if t][:6]


def _first(obj, attrs):
    for attr in attrs:
        value = getattr(obj, attr, None)
        if value not in (None, ""):
            return str(value)
    return ""


def _score(haystack, terms, whole):
    """Higher is better. Rewards matching the start of the text, so typing
    "sup" puts Supplier above "Broiler Farm Supervisor"."""
    text = haystack.lower()
    if text == whole:
        return 100
    if text.startswith(whole):
        return 80
    if whole and whole in text:
        return 60
    # every term matched somewhere, else the caller would not have kept it
    return 40 - min(len(text), 39)


def search_pages(user, query, viewable=None):
    """Tabs the user may view whose label / section / module matches."""
    terms = [t.lower() for t in _terms(query)]
    if not terms:
        return []
    whole = " ".join(terms)
    viewable = allowed_view_tabs(user) if viewable is None else viewable

    hits = []
    for module in MODULE_REGISTRY:
        nav, nav_label = module["nav"], module["label"]
        icon, colour = NAV_ICONS.get(nav, DEFAULT_ICON)
        for section in module["sections"]:
            for tab in section["tabs"]:
                code, label = tab[0], tab[1]
                if code not in viewable:
                    continue
                # The code is in the haystack so the short names people
                # actually type ("coa", "gc_settlement") find their page even
                # though the label spells the words out.
                haystack = (f"{nav_label} {section['label']} {label} "
                            f"{code.replace('_', ' ')}").lower()
                if not all(t in haystack for t in terms):
                    continue
                try:
                    url = reverse(code)
                except NoReverseMatch:
                    continue        # a tab whose code is not a routable page
                hits.append({
                    "kind": "page",
                    "title": label,
                    "subtitle": f"{nav_label} › {section['label']}",
                    "url": url,
                    "icon": icon,
                    "colour": colour,
                    "score": _score(label, terms, whole),
                })
    hits.sort(key=lambda h: (-h["score"], h["title"]))
    return hits


def search_records(user, query, viewable=None):
    """Master records matching the query, from modules the user may view."""
    terms = _terms(query)
    if not terms:
        return []
    whole = " ".join(terms).lower()
    viewable = allowed_view_tabs(user) if viewable is None else viewable

    hits = []
    for source in RECORD_SOURCES:
        if source.tab not in viewable:
            continue
        try:
            url = reverse(source.tab)
        except NoReverseMatch:
            continue
        model = _load(source.model_path)

        # Each word must appear in at least one field; a word may match a
        # different field from its neighbour ("ganga farm" -> name + place).
        filters = Q()
        for term in terms:
            word = Q()
            for field in source.fields:
                word |= Q(**{f"{field}__icontains": term})
            filters &= word

        icon, colour = NAV_ICONS.get(_TAB_NAV.get(source.tab, ""), DEFAULT_ICON)
        for obj in model.objects.filter(filters)[:PER_SOURCE_LIMIT]:
            title = _first(obj, source.title) or str(obj)
            bits = [b for b in (_first(obj, [a]) for a in source.subtitle) if b]
            hits.append({
                "kind": source.kind,
                "title": title,
                "subtitle": " · ".join([source.kind] + bits),
                "url": f"{url}?{FIND_PARAM}={quote(title)}",
                "icon": icon,
                "colour": colour,
                "score": _score(title, terms, whole),
            })
    hits.sort(key=lambda h: (-h["score"], h["title"]))
    return hits[:RECORD_LIMIT]


def global_search(user, query):
    """``{"pages": [...], "records": [...], "total": n}`` for the dashboard."""
    query = (query or "").strip()
    if len(query) < 2:
        return {"pages": [], "records": [], "total": 0, "query": query}

    viewable = allowed_view_tabs(user)
    pages = search_pages(user, query, viewable)
    records = search_records(user, query, viewable)
    return {
        "query": query,
        "pages": pages[:PAGE_LIMIT],
        "more_pages": max(0, len(pages) - PAGE_LIMIT),
        "records": records,
        "total": len(pages) + len(records),
    }
