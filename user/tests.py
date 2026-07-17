from django.contrib.auth.models import Group as AuthGroup, User
from django.test import TestCase
from django.urls import reverse

from hr.models import Designation, Group as HrGroup
from inventory.models import Warehouse
from user.models import GroupTabPermission


class HomeTrackingWidgetTests(TestCase):
    """The home page embeds a live tracking widget, gated by Web-Access."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="pass12345")
        self.client.login(username="tester", password="pass12345")

    def test_superuser_sees_widget_and_leaflet_assets(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Field Team")
        self.assertContains(response, "home-trk-map")
        self.assertContains(response, "leaflet")

    def test_superuser_sees_sync_button_wired_to_the_sync_endpoint(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'id="home-trk-sync"')
        self.assertContains(response, reverse("api_tracking_sync_now"))

    def test_superuser_sees_route_bar_wired_to_route_endpoint(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'id="home-trk-route-bar"')
        self.assertContains(response, 'id="home-trk-route-back"')
        self.assertContains(response, "has-routes")
        self.assertContains(response, reverse("api_tracking_route"))

    def test_superuser_sees_filter_bar_populated_with_real_options(self):
        self.user.is_superuser = True
        self.user.save()
        Warehouse.objects.create(name="Akbarpur Branch")
        HrGroup.objects.create(name="Sales Team")
        Designation.objects.create(title="Field Officer")
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'id="home-trk-q"')
        self.assertContains(response, 'id="home-trk-warehouse"')
        self.assertContains(response, "Akbarpur Branch")
        self.assertContains(response, "Sales Team")
        self.assertContains(response, "Field Officer")

    def test_dashboard_only_user_cannot_click_into_routes(self):
        """Granting only Live Dashboard (not Route History) must not expose
        the route-click affordance, since api_tracking_route requires the
        separate tracking_routes permission and would 403 for this user."""
        group = AuthGroup.objects.create(name="Dashboard Only")
        self.user.groups.add(group)
        GroupTabPermission.objects.create(
            group=group, tab_code="tracking_dashboard", can_view=True)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Field Team")
        self.assertNotContains(response, 'id="home-trk-route-bar"')
        # The CSS rule ".has-routes { ... }" is static and always present for
        # any tracking_dashboard user; what must NOT happen is the class
        # actually being applied to the list element.
        self.assertNotContains(response, 'home-trk-list has-routes')
        self.assertNotContains(response, "Route History")

    def test_restricted_user_without_tracking_tab_sees_no_widget(self):
        group = AuthGroup.objects.create(name="Restricted")
        self.user.groups.add(group)
        # Any configured row activates the matrix; grant an unrelated tab only.
        GroupTabPermission.objects.create(
            group=group, tab_code="employee_list", can_view=True)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Field Team")
        self.assertNotContains(response, "home-trk-map")
        self.assertNotContains(response, "leaflet")

    def test_user_granted_tracking_tab_sees_widget(self):
        group = AuthGroup.objects.create(name="Tracking Viewers")
        self.user.groups.add(group)
        GroupTabPermission.objects.create(
            group=group, tab_code="tracking_dashboard", can_view=True)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Field Team")
        self.assertContains(response, "home-trk-map")

    def test_home_page_renders_for_unconfigured_user(self):
        # No matrix configured anywhere -> unrestricted, matches existing
        # "not yet applied" behaviour for pre-existing accounts.
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Field Team")
