"""Every phone register that is looked up by date says so, and says it right.

One line of config — `dateField` — gives a mobile register its From/To controls
and the seven-day window it opens on. That makes it two things at once: a
feature switch, and a field name that has to match what the API returns.

Both halves fail silently. A register that omits it has no date controls at
all, which nobody notices until someone goes looking for last month's records
and has to scroll. A register that names the wrong field filters every row out
and looks empty, which reads as "nothing was ever filed here" — the worse of
the two, because it looks like missing data rather than a missing filter.

So this checks the config against the models the endpoints actually serve, and
requires a date-bearing transaction register to declare one rather than
leaving it to whoever adds the next screen to remember.
"""
import os
import re

from django.db import models as dj
from django.test import SimpleTestCase
from django.urls import get_resolver

MOBILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "mobile", "src")

#: Sections of the phone's module hubs whose screens are registers of dated
#: events rather than master data. "Transactions" is the app's own word for
#: most of them; the other two are named for what they hold.
REGISTER_SECTIONS = {"Transactions", "Attendance", "Employee Trip And Route"}

#: Registers deliberately without a range, with the reason.
NO_RANGE = {
    # A workflow item, not a dated event: it carries only the timestamp it was
    # raised at, which is not what anyone would filter it by.
    "broiler-farmer-farm-setup-request",
}


def _catalog():
    with open(os.path.join(MOBILE, "config", "catalog.ts"), encoding="utf-8") as fh:
        return fh.read()


def _entries(source):
    """resource key -> (path, declared dateField or None)."""
    out = {}
    for match in re.finditer(r'key: "([a-z0-9-]+)",\n\s*module: "[a-z_]+",\n\s*path: "([^"]+)"',
                             source):
        key, path = match.group(1), match.group(2)
        block = source[match.start():]
        nxt = block.find('\n    key: "', 1)
        block = block[:nxt] if nxt != -1 else block
        field = re.search(r'dateField: "([a-z_]+)"', block)
        out[key] = (path, field.group(1) if field else None)
    return out


def _register_keys(source):
    """Resource keys sitting in a hub section that lists dated registers."""
    tail = source.split("export const MODULES")[1]
    keys, section = set(), None
    for line in tail.split("\n"):
        title = re.match(r'\s*title: "([^"]+)",\s*$', line)
        if title:
            section = title.group(1)
            continue
        item = re.match(r'\s*"([a-z0-9-]+)",\s*$', line)
        if item and section in REGISTER_SECTIONS:
            keys.add(item.group(1))
    return keys


def _models_by_path():
    """Endpoint path -> the model behind it, read off the live router."""
    get_resolver().url_patterns          # imports every app's views/routers
    import api.urls as api_urls

    out = {}
    for attr in dir(api_urls):
        registry = getattr(getattr(api_urls, attr), "registry", None)
        if not registry:
            continue
        for prefix, viewset, _basename in registry:
            model = getattr(getattr(viewset, "queryset", None), "model", None)
            if model is not None:
                out["/%s/" % prefix] = model
    return out


def _usable_date_fields(model):
    """Date fields a register could sensibly filter on.

    DateTimeFields and the auto stamps are excluded: `created_at` is when a row
    was typed, not when the thing happened, and a register filters on the
    latter — the same distinction hatchery/change_requests.py draws.
    """
    return [f.name for f in model._meta.concrete_fields
            if isinstance(f, dj.DateField) and not isinstance(f, dj.DateTimeField)
            and not getattr(f, "auto_now", False)
            and not getattr(f, "auto_now_add", False)]


class MobileDateFieldTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = _catalog()
        cls.entries = _entries(cls.source)
        cls.registers = _register_keys(cls.source)
        cls.models = _models_by_path()

    def model_for(self, key):
        path, _ = self.entries[key]
        return self.models.get(path.split("?")[0])

    def test_the_catalog_and_the_router_were_both_read(self):
        """A guard on the guard: an empty parse would pass every test below."""
        self.assertGreater(len(self.entries), 60)
        self.assertGreater(len(self.registers), 20)
        self.assertGreater(len(self.models), 60)

    def test_every_declared_date_field_exists_on_its_model(self):
        """The silent one. A misspelled field matches no row, and the register
        renders as though nothing was ever filed in it."""
        wrong = {}
        for key, (path, field) in sorted(self.entries.items()):
            if not field:
                continue
            model = self.models.get(path.split("?")[0])
            if model is None:
                continue
            if field not in {f.name for f in model._meta.concrete_fields}:
                wrong[key] = "%s has no field %r" % (model.__name__, field)
        self.assertEqual(wrong, {})

    def test_every_declared_date_field_is_a_date(self):
        """The range compares ISO strings, so a number or a name would filter
        by something meaningless rather than fail."""
        wrong = {}
        for key, (path, field) in sorted(self.entries.items()):
            if not field:
                continue
            model = self.models.get(path.split("?")[0])
            if model is None:
                continue
            f = model._meta.get_field(field)
            if not isinstance(f, dj.DateField):
                wrong[key] = "%s.%s is %s" % (model.__name__, field,
                                              f.get_internal_type())
        self.assertEqual(wrong, {})

    def test_no_register_filters_on_when_the_row_was_typed(self):
        """created_at is not the transaction date. Filtering on it would show
        a backdated entry under the day someone got round to keying it."""
        wrong = []
        for key, (path, field) in sorted(self.entries.items()):
            if not field:
                continue
            model = self.models.get(path.split("?")[0])
            if model is None:
                continue
            f = model._meta.get_field(field)
            if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
                wrong.append(key)
        self.assertEqual(wrong, [])

    def test_every_dated_register_offers_a_range(self):
        """The rule that keeps this from rotting: a register of dated events
        gets the controls, and the next one added inherits the requirement
        rather than depending on whoever adds it having seen this."""
        missing = []
        for key in sorted(self.registers):
            if key in NO_RANGE or key not in self.entries:
                continue
            _, field = self.entries[key]
            model = self.model_for(key)
            if model is None or not _usable_date_fields(model):
                continue                      # nothing to filter on
            if not field:
                missing.append(key)
        self.assertEqual(missing, [],
                         "these registers have a date but no From/To range")

    def test_a_register_excused_from_the_range_really_has_no_date(self):
        """Otherwise the exemption list becomes a place to park screens that
        were simply never finished."""
        undeserved = []
        for key in sorted(NO_RANGE):
            model = self.model_for(key)
            if model is not None and _usable_date_fields(model):
                undeserved.append("%s (%s)" % (key, _usable_date_fields(model)))
        self.assertEqual(undeserved, [],
                         "these have a date to filter on and should offer it")
