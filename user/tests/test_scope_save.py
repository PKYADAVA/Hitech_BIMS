"""What the Web-Access editor actually stores when a scope is narrowed.

The reported symptom: with "All branches" on, every list is full; switch it off
and pick specific branches, and the lists come up empty. That is either the
scoping refusing to match, or the editor not saving the branches that were
picked — and those need opposite fixes, so this posts what the form posts and
reads back what landed.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from broiler.models import Branch, BroilerFarm, Farmer, Region, Supervisor
from inventory.models import Warehouse
from user.models import GroupAccessProfile


class ScopeSaveTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(description="East")
        self.b1 = Branch.objects.create(branch_name="Akbarpur", region=self.region,
                                        prefix="AKB")
        self.b2 = Branch.objects.create(branch_name="Bahraich", region=self.region,
                                        prefix="BHR")
        self.w1 = Warehouse.objects.create(name="Akbarpur Store")
        sup = Supervisor.objects.create(branch=self.b1, name="R. Verma")
        farmer = Farmer.objects.create(farmer_name="S. Yadav")
        self.f1 = BroilerFarm.objects.create(branch=self.b1, supervisor=sup, farmer=farmer,
                                             region=self.region, line="L1",
                                             farm_name="Farm One", farm_capacity=5000)
        self.f2 = BroilerFarm.objects.create(branch=self.b2, supervisor=sup, farmer=farmer,
                                             region=self.region, line="L1",
                                             farm_name="Farm Two", farm_capacity=5000)

        self.group = Group.objects.create(name="Branch Manager")
        self.admin = User.objects.create_superuser("boss", "b@x.com", "Str0ngPass!")
        self.client.force_login(self.admin)

    def save_scope(self, **post):
        """POST the editor form the way the page does."""
        body = {"group": self.group.id, "name": self.group.name,
                "access_type": "sub_admin", "login_type": "password"}
        body.update(post)
        resp = self.client.post(reverse("user_groups"), body)
        self.assertIn(resp.status_code, (200, 302))
        return GroupAccessProfile.objects.get(group=self.group)

    # ---- what the switches store -------------------------------------------

    def test_all_on_stores_all_and_keeps_nothing_selected(self):
        """Every switch on is the unconfigured shape: unrestricted."""
        profile = self.save_scope(**{f"all_{f}": "on" for f in
                                     ("branches", "lines", "farms", "sectors",
                                      "customer_groups", "supplier_groups")})
        self.assertTrue(profile.all_branches)
        self.assertEqual(profile.branches.count(), 0)

    def test_switching_all_off_and_picking_branches_stores_them(self):
        """The reported case. If the picked branches do not land here, no
        amount of scoping arithmetic downstream can be right."""
        profile = self.save_scope(**{
            "all_lines": "on", "all_farms": "on", "all_sectors": "on",
            "all_customer_groups": "on", "all_supplier_groups": "on",
            "branches[]": [str(self.b1.id)],
        })
        self.assertFalse(profile.all_branches)
        self.assertEqual(list(profile.branches.values_list("id", flat=True)),
                         [self.b1.id])

    def test_a_narrowed_group_then_sees_that_branch_and_its_farms(self):
        """End to end: save through the editor, then read as a member would."""
        from user.services.scoping import branches_for, farms_for

        self.save_scope(**{
            "all_lines": "on", "all_farms": "on", "all_sectors": "on",
            "all_customer_groups": "on", "all_supplier_groups": "on",
            "branches[]": [str(self.b1.id)],
        })
        member = User.objects.create_user("member", "m@x.com", "Str0ngPass!")
        member.groups.add(self.group)

        self.assertEqual(list(branches_for(member, Branch.objects.all())
                              .values_list("branch_name", flat=True)), ["Akbarpur"])
        # Farms are left on "All", and still narrow to the branch — a branch
        # login seeing another branch's farms would make the scope pointless.
        self.assertEqual(list(farms_for(member).values_list("farm_name", flat=True)),
                         ["Farm One"])

    def test_all_off_with_nothing_picked_stores_a_real_nothing(self):
        """Not a bug, but the trap: it means nothing, not everything, and the
        lists that read it are empty until someone picks a row."""
        profile = self.save_scope(**{
            "all_lines": "on", "all_farms": "on", "all_sectors": "on",
            "all_customer_groups": "on", "all_supplier_groups": "on",
        })
        self.assertFalse(profile.all_branches)
        self.assertEqual(profile.branches.count(), 0)

        member = User.objects.create_user("member2", "m2@x.com", "Str0ngPass!")
        member.groups.add(self.group)
        from user.services.scoping import allowed_ids

        self.assertEqual(allowed_ids(member, "branches"), set())

    def test_re_saving_does_not_lose_the_selection(self):
        """The editor is opened and saved repeatedly; a second save that drops
        the picked branches would look exactly like the reported symptom."""
        self.save_scope(**{
            "all_lines": "on", "all_farms": "on", "all_sectors": "on",
            "all_customer_groups": "on", "all_supplier_groups": "on",
            "branches[]": [str(self.b1.id)],
        })
        profile = self.save_scope(**{
            "all_lines": "on", "all_farms": "on", "all_sectors": "on",
            "all_customer_groups": "on", "all_supplier_groups": "on",
            "branches[]": [str(self.b1.id)],
        })
        self.assertEqual(list(profile.branches.values_list("id", flat=True)),
                         [self.b1.id])

    # ---- what the editor renders back ---------------------------------------

    def test_the_editor_shows_the_saved_selection_back(self):
        """A picked branch that does not come back selected would be un-picked
        by the next save, silently."""
        self.save_scope(**{
            "all_lines": "on", "all_farms": "on", "all_sectors": "on",
            "all_customer_groups": "on", "all_supplier_groups": "on",
            "branches[]": [str(self.b1.id)],
        })
        page = self.client.get(reverse("user_groups"),
                               {"group": self.group.id}).content.decode()
        marker = f'<option value="{self.b1.id}" selected>'
        self.assertIn(marker, page.replace(" selected ", " selected>").replace(
            f'value="{self.b1.id}" selected', f'value="{self.b1.id}" selected'))
