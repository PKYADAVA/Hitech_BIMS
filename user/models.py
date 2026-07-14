# user/models.py
from django.contrib.auth.models import Group, User
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    department = models.CharField(max_length=100, blank=True, null=True)
    role = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.user.username


class GroupTabPermission(models.Model):
    """Per-group action permissions for one screen (tab) of the ERP.

    ``tab_code`` is the stable code from ``user.access.MODULE_REGISTRY`` (also the
    primary URL name for the page). One row per (group, tab); the seven booleans
    are the matrix columns.
    """

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="tab_permissions"
    )
    tab_code = models.CharField(max_length=100)
    can_view = models.BooleanField(default=False)
    can_add = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)
    can_print = models.BooleanField(default=False)
    can_save = models.BooleanField(default=False)
    can_update = models.BooleanField(default=False)
    can_favorite = models.BooleanField(default=False)

    class Meta:
        unique_together = ("group", "tab_code")
        verbose_name = "Group tab permission"

    def __str__(self):
        return f"{self.group.name} · {self.tab_code}"


class GroupAccessProfile(models.Model):
    """Data-scoping and account-level flags for a group (screenshot: Branch /
    Line / Farm / Sector / Customer & Supplier group access, plus Access Type,
    Login Type and Dashboard toggles).

    Each scope has an ``all_*`` flag. When it is True the group is scoped to
    *all* records of that type and the specific M2M selection is ignored;
    when False, access is limited to the selected records.
    """

    ACCESS_TYPE_CHOICES = [("admin", "Admin"), ("sub_admin", "Sub-Admin")]
    LOGIN_TYPE_CHOICES = [("password", "Password"), ("otp", "OTP")]

    group = models.OneToOneField(
        Group, on_delete=models.CASCADE, related_name="access_profile"
    )

    is_superuser = models.BooleanField(default=False)
    access_type = models.CharField(
        max_length=10, choices=ACCESS_TYPE_CHOICES, default="sub_admin"
    )
    login_type = models.CharField(
        max_length=10, choices=LOGIN_TYPE_CHOICES, default="password"
    )
    sale_multiple_edit = models.BooleanField(default=False)
    sale_multiple_delete = models.BooleanField(default=False)
    dashboard = models.BooleanField(default=True)

    # Data scoping. "All" flags default True so an unconfigured group is not
    # accidentally scoped to nothing.
    all_branches = models.BooleanField(default=True)
    branches = models.ManyToManyField(
        "broiler.Branch", blank=True, related_name="access_profiles"
    )
    all_lines = models.BooleanField(default=True)
    lines = models.ManyToManyField(
        "broiler.BroilerLine", blank=True, related_name="access_profiles"
    )
    all_farms = models.BooleanField(default=True)
    farms = models.ManyToManyField(
        "broiler.BroilerFarm", blank=True, related_name="access_profiles"
    )
    all_sectors = models.BooleanField(default=True)
    sectors = models.ManyToManyField(
        "inventory.Warehouse", blank=True, related_name="access_profiles"
    )
    all_customer_groups = models.BooleanField(default=True)
    customer_groups = models.ManyToManyField(
        "sales.CustomerGroup", blank=True, related_name="access_profiles"
    )
    all_supplier_groups = models.BooleanField(default=True)
    supplier_groups = models.ManyToManyField(
        "purchase.VendorGroup", blank=True, related_name="access_profiles"
    )

    def __str__(self):
        return f"Access profile · {self.group.name}"
