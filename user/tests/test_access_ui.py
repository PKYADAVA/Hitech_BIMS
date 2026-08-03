"""The access editors driven in a real browser.

Everything else in this package checks what the server renders and what it
saves. None of it can press a folder toggle or a column header — and that half
of these pages was rewritten onto shared JavaScript (static/js/access_tree.js),
replacing three separate implementations. A silent failure there looks like a
page that renders perfectly and simply does nothing when clicked, which is
exactly the shape of bug the server suite cannot see.

Skipped automatically when Playwright or its Chromium build is absent, so it
costs nothing in an environment that has neither:

    pip install playwright && playwright install chromium
    python manage.py test user.tests.test_access_ui
"""
import os
import unittest

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from user.models import GroupDashboardWidget, GroupTabPermission

try:
    from playwright.sync_api import sync_playwright
except ImportError:                                   # pragma: no cover
    sync_playwright = None


def _chromium_available():
    if sync_playwright is None:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_chromium_available(), "Playwright chromium not installed")
class AccessEditorUiTests(StaticLiveServerTestCase):
    """One browser, all three editors, driven the way an administrator would."""

    @classmethod
    def setUpClass(cls):
        # Playwright's sync API runs an event loop in this thread, and Django
        # then refuses ORM calls as async-unsafe — so this class cannot even
        # create its own fixtures. The loop belongs to the browser driver, not
        # to Django, and every query here is on the test's own connection.
        #
        # Scoped to this class and restored afterwards, deliberately: setting
        # it at import time would apply to the whole test process and mask a
        # genuine async-safety bug in some unrelated test that never asked for
        # the exemption.
        cls._async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "1"
        super().setUpClass()
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()
        super().tearDownClass()
        if cls._async_unsafe is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls._async_unsafe

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("ui_admin", "u@x.com", "Str0ngPass!")
        self.group = Group.objects.create(name="UI Group")
        # Two screens fully granted and one withheld, so the page has both a
        # tickable row and a disabled one to prove the cascade respects.
        for tab in ("daily_entry_list", "bird_sale_list"):
            GroupTabPermission.objects.create(
                group=self.group, tab_code=tab, can_view=True, can_add=True,
                can_edit=True, can_delete=True)
        GroupDashboardWidget.objects.create(group=self.group,
                                            widget_key="live_flock",
                                            enabled=True, position=0)

        # A session rather than a login form: this is about the editors, not
        # about authentication, and it keeps the test independent of it.
        store = SessionStore()
        store["_auth_user_id"] = str(self.admin.pk)
        store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
        store["_auth_user_hash"] = self.admin.get_session_auth_hash()
        store.create()

        self.ctx = self._browser.new_context(viewport={"width": 1500, "height": 950})
        self.ctx.add_cookies([{"name": "sessionid", "value": store.session_key,
                               "url": self.live_server_url}])
        self.page = self.ctx.new_page()
        self.errors = []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))

    def tearDown(self):
        self.ctx.close()

    def open(self, path):
        self.page.goto(self.live_server_url + path, wait_until="networkidle")
        self.page.wait_for_timeout(200)
        self.assertEqual(self.errors, [], f"JS errors on {path}")

    # ---- the shared tree ---------------------------------------------------

    def test_the_shared_script_is_served(self):
        """A 404 here disables every cascade and folder on all three pages,
        while the markup still renders perfectly."""
        response = self.page.request.get(
            self.live_server_url + "/static/js/access_tree.js")
        self.assertEqual(response.status, 200)
        self.assertIn("data-access-tree", response.text())

    def test_a_folder_collapses_and_re_expands(self):
        self.open(f"/mobile-access/form/?group={self.group.id}")
        toggle = self.page.locator(".at-toggle").first
        folder = toggle.get_attribute("data-at-folder")
        kids = self.page.locator(f".child-of-{folder}")
        self.assertTrue(kids.first.is_visible())

        toggle.click()
        self.page.wait_for_timeout(150)
        self.assertFalse(kids.first.is_visible())

        toggle.click()
        self.page.wait_for_timeout(150)
        self.assertTrue(kids.first.is_visible())

    def test_a_column_header_ticks_its_whole_column(self):
        self.open(f"/mobile-access/form/?group={self.group.id}")
        header = self.page.locator(".at-all[data-action='view']").first
        cells = self.page.locator(".at-cell[data-action='view']:not([disabled])")
        total = cells.count()
        self.assertGreater(total, 0)

        header.check()
        self.page.wait_for_timeout(200)
        self.assertEqual(sum(1 for i in range(total) if cells.nth(i).is_checked()), total)

        header.uncheck()
        self.page.wait_for_timeout(200)
        self.assertEqual(sum(1 for i in range(total) if cells.nth(i).is_checked()), 0)

    def test_a_cascade_never_ticks_a_disabled_cell(self):
        """A disabled box is a permission the web matrix withholds. A bulk tick
        must not promise it — and a disabled input does not even submit, so the
        page would be claiming access that could never be saved."""
        self.open(f"/mobile-access/form/?group={self.group.id}")
        blocked = self.page.locator(".at-cell[disabled]")
        self.assertGreater(blocked.count(), 0, "no withheld screen to test against")

        self.page.locator(".at-all").first.check()
        self.page.wait_for_timeout(250)
        stuck = sum(1 for i in range(blocked.count()) if blocked.nth(i).is_checked())
        self.assertEqual(stuck, 0)

    def test_reordering_renumbers_the_positions(self):
        """The position inputs are what the save reads, so the row order and
        the numbers have to agree after a move."""
        self.open(f"/mobile-access/form/?group={self.group.id}")
        first_key = self.page.locator(".ma-modrow").first.get_attribute("data-key")
        self.page.locator(".at-move[data-at-dir='down']").first.click()
        self.page.wait_for_timeout(200)

        self.assertNotEqual(
            self.page.locator(".ma-modrow").first.get_attribute("data-key"), first_key)
        positions = self.page.locator(".at-pos")
        values = [positions.nth(i).input_value() for i in range(4)]
        self.assertEqual(values, ["0", "1", "2", "3"])

    # ---- the other editors on the same script ------------------------------

    def test_the_web_access_matrix_still_cascades(self):
        """The largest of the three, and the one already in production."""
        self.open(f"/manage_groups/?group={self.group.id}")
        header = self.page.locator(".at-all[data-action='view']").first
        cells = self.page.locator(".at-cell[data-action='view']:not([disabled])")
        total = cells.count()
        self.assertGreater(total, 100, "expected the full ERP matrix")

        header.check()
        self.page.wait_for_timeout(400)
        self.assertEqual(sum(1 for i in range(total) if cells.nth(i).is_checked()), total)

    def test_dashboard_access_reorders_without_folders(self):
        """It is a flat list by design — the shared script must not require a
        tree to work."""
        self.open(f"/dashboard-access/form/?group={self.group.id}")
        self.assertEqual(self.page.locator(".at-toggle").count(), 0)

        first_key = self.page.locator(".da-row").first.get_attribute("data-key")
        self.page.locator(".at-move[data-at-dir='down']").first.click()
        self.page.wait_for_timeout(200)
        self.assertNotEqual(
            self.page.locator(".da-row").first.get_attribute("data-key"), first_key)

    # ---- the read-only pages -----------------------------------------------

    def test_the_audit_page_loads_clean(self):
        self.open("/access-changes/")
