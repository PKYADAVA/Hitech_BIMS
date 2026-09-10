"""The phone's approval-queue fallbacks, kept in step with the web.

A user without the edit or delete right on a module does not lose the ability
to act on a record — the web register swaps Edit and Delete for "Request
modification" and "Request deletion", which queue the change for someone who
holds the right. The phone offers the same two, driven by two hand-written
maps in mobile/src/config/changeRequestModules.ts.

Hand-written maps go stale silently. The first of them was written when nine
modules were registered and was never extended as twenty more arrived, so on
those twenty a restricted user saw no fallback at all. Nothing failed, because
nothing was checking. These tests are that check: they read the maps out of the
TypeScript and hold them against the modules the backend actually registers and
the buttons the web templates actually draw.
"""
import glob
import os
import re

from django.test import SimpleTestCase
from django.urls import get_resolver

from hatchery.change_requests import CHANGE_REQUEST_HANDLERS

MOBILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "mobile", "src")

#: tab_code -> the list template that draws its Actions column, where the two
#: do not share a name. Both of these are delete-only, so the aliases do not
#: affect the edit set — they exist so that a tab whose template cannot be
#: found is a failure rather than a silent gap.
TEMPLATE_ALIASES = {
    "stock_issue_list": "stock_issued_list",
    "stock_receive_list": "stock_received_list",
}


def _read(*parts):
    with open(os.path.join(MOBILE, *parts), encoding="utf-8") as fh:
        return fh.read()


def _ts_record(source, name):
    """The "key": "value" pairs of an `export const <name>: Record<...> = {}`."""
    body = source.split("export const %s" % name)[1].split("};")[0]
    return dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', body))


def _ts_set(source, name):
    """The members of an `export const <name> = new Set<string>([...])`."""
    body = source.split("export const %s" % name)[1].split("]);")[0]
    return set(re.findall(r'"([^"]+)"', body))


def _mobile():
    src = _read("config", "changeRequestModules.ts")
    return _ts_record(src, "CHANGE_REQUEST_MODULE"), _ts_set(src, "REQUEST_EDIT_MODULES")


def _resource_tabs():
    return _ts_record(_read("api", "permissions.ts"), "RESOURCE_TABS")


class MobileChangeRequestMapTests(SimpleTestCase):
    """Every module the phone can reach, it can also raise a request against."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Handlers register from each app's views.py, which Django imports via
        # the URLconf — untouched, this dict is empty in a bare test process.
        get_resolver().url_patterns
        cls.modules, cls.edit_modules = _mobile()
        cls.resource_tabs = _resource_tabs()
        cls.tab_to_module = {h["tab"]: k for k, h in CHANGE_REQUEST_HANDLERS.items()}

    def eligible(self):
        """Mobile resource -> module, for every resource whose tab the backend
        has a change-request handler for."""
        return {rk: self.tab_to_module[tab]
                for rk, tab in self.resource_tabs.items() if tab in self.tab_to_module}

    def test_the_backend_registers_the_modules_this_test_reasons_about(self):
        """A guard on the guard: these tests are worthless against an empty
        registry, which is what a bare test process would otherwise see."""
        self.assertGreater(len(CHANGE_REQUEST_HANDLERS), 20)

    def test_every_reachable_module_offers_a_deletion_request(self):
        """The original bug. A resource the phone lists, whose module the web
        takes requests for, must offer the fallback — otherwise a restricted
        user is shown a record they can neither change nor ask to have
        changed."""
        missing = sorted(rk for rk in self.eligible() if rk not in self.modules)
        self.assertEqual(missing, [],
                         "these resources show no Request Deletion on the phone")

    def test_no_resource_is_mapped_to_a_module_the_backend_does_not_have(self):
        """A wrong key is worse than a missing one: the button appears, and
        fails with a 400 only once someone presses it."""
        unknown = sorted(m for m in self.modules.values()
                         if m not in CHANGE_REQUEST_HANDLERS)
        self.assertEqual(unknown, [], "no handler is registered for these modules")

    def test_each_resource_is_mapped_to_its_own_modules_key(self):
        """Two registers of the same shape are easy to transpose, and the
        request would then be raised against the wrong record entirely."""
        eligible = self.eligible()
        wrong = {rk: (mapped, eligible[rk]) for rk, mapped in self.modules.items()
                 if rk in eligible and mapped != eligible[rk]}
        self.assertEqual(wrong, {}, "mapped module != the module of the resource's tab")

    def test_every_mapped_resource_is_one_the_phone_actually_lists(self):
        """A mapping for a resource key that no longer exists is dead weight
        that reads as coverage."""
        strays = sorted(rk for rk in self.modules if rk not in self.resource_tabs)
        self.assertEqual(strays, [], "not resources in RESOURCE_TABS")


class MobileEditRequestTests(MobileChangeRequestMapTests):
    """The edit half, which the phone was missing entirely."""

    def web_edit_modules(self):
        """The modules whose web register draws a Request modification button.

        Read from the templates rather than the URLconf because not every one
        of them is a link — Stock Transfer opens a modal on the same page, and
        a URL-based check would call it unsupported.
        """
        templates = {os.path.basename(p)[:-5]: p
                     for p in glob.glob("*/templates/*.html")}
        found, unreadable = set(), []
        for module, handler in CHANGE_REQUEST_HANDLERS.items():
            tab = handler["tab"]
            path = templates.get(TEMPLATE_ALIASES.get(tab, tab))
            if path is None:
                unreadable.append((module, tab))
                continue
            with open(path, encoding="utf-8") as fh:
                if "request-edit" in fh.read():
                    found.add(module)
        self.assertEqual(unreadable, [],
                         "no list template found for these tabs — add an alias")
        return found

    def test_the_phone_offers_an_edit_request_wherever_the_web_does(self):
        """Mirrored rather than decided here. A module offers edit requests
        only when a correction can be replayed as one payload, and the web
        register is where that judgement already lives."""
        reachable = set(self.modules.values())
        self.assertEqual(self.edit_modules, self.web_edit_modules() & reachable)

    def test_no_edit_request_is_offered_where_the_web_withholds_one(self):
        """The stricter half, stated on its own because it is the one that
        would queue a request nobody can safely approve — a Daily Entry
        correction replayed out of the chain it belongs to, say."""
        overreach = sorted(self.edit_modules - self.web_edit_modules())
        self.assertEqual(overreach, [], "the web offers no edit request for these")

    def test_an_edit_module_is_one_the_phone_can_also_reach(self):
        """REQUEST_EDIT_MODULES narrows CHANGE_REQUEST_MODULE; a module in the
        first and not the second is unreachable and reads as supported."""
        orphans = sorted(self.edit_modules - set(self.modules.values()))
        self.assertEqual(orphans, [], "not reachable from any mobile resource")


class MobileEditFormTests(SimpleTestCase):
    """A proposal is a payload, so a module that takes edit requests needs a
    form on the phone to build one."""

    def test_every_edit_module_has_a_resource_with_an_edit_form(self):
        modules, edit_modules = _mobile()
        resource_of = {m: rk for rk, m in modules.items()}
        sources = [_read("navigation", "openForm.ts"),
                   _read("config", "documents.ts"),
                   _read("config", "forms.ts")]
        formless = [resource_of[m] for m in sorted(edit_modules)
                    if not any('"%s"' % resource_of[m] in s for s in sources)]
        self.assertEqual(formless, [],
                         "these offer Request Edit with no form to fill in")

    def test_an_edit_proposal_submits_through_one_shared_path(self):
        """Eight screens can raise a proposal. Each building its own request is
        how one of them ends up sending the wrong shape, which an approval
        would then write to the record.

        Only the edit action is held to this. A deletion request carries no
        payload — there is nothing to get wrong about its shape — so the list
        screen raising one directly is not the same thing.
        """
        direct = []
        for path in glob.glob(os.path.join(MOBILE, "screens", "*.tsx")):
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for call in re.findall(r"createChangeRequest\((?:[^;]{0,200})", source):
                if '"edit"' in call:
                    direct.append(os.path.basename(path))
                    break
        self.assertEqual(sorted(direct), [],
                         "call submitEditProposal (net/proposeEdit) instead")
