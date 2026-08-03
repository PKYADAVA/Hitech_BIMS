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


class WebAccessAudit(models.Model):
    """What the Web-Access guard *would* do, recorded without doing it.

    The guard currently allows any URL it cannot map to a tab, which is most of
    them. Turning that around blind would lock real users out of endpoints
    nobody realised were in use, so enforcement ships dark: every request that
    is unmapped — or that would be refused once the mapping is complete — lands
    here instead. Read the table after a normal day's work and the allowlist
    writes itself.

    One row per (url name, method, verdict, user); ``hits`` counts repeats so
    the table stays small enough to read.
    """

    UNMAPPED = "unmapped"     # no tab owns this url — today it is simply open
    DENIED = "denied"         # mapped, and the matrix says no (already enforced)

    VERDICTS = [(UNMAPPED, "Unmapped"), (DENIED, "Denied")]

    url_name = models.CharField(max_length=200, db_index=True)
    method = models.CharField(max_length=10)
    verdict = models.CharField(max_length=20, choices=VERDICTS, db_index=True)
    username = models.CharField(max_length=150)
    path = models.CharField(max_length=300, blank=True)
    view = models.CharField(max_length=200, blank=True,
                            help_text="Dotted path of the view that served it")
    tab_code = models.CharField(max_length=100, blank=True)
    action = models.CharField(max_length=20, blank=True)
    hits = models.PositiveIntegerField(default=1)
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Web access audit"
        verbose_name_plural = "Web access audit"
        unique_together = ("url_name", "method", "verdict", "username")
        ordering = ["url_name", "username"]

    def __str__(self):
        return f"{self.verdict}: {self.method} {self.url_name} ({self.username})"


class GroupMobileAccess(models.Model):
    """Which mobile-app modules a group sees, and in what order.

    The phone used to show whatever the web tab matrix allowed — there was no
    way to give someone a screen at their desk but keep it off their phone.
    This is that second switch, and like ``GroupDashboardWidget`` it is
    **subtractive only**: a module appears on the phone when the tab matrix
    allows it *and* it is enabled here. Turning one on cannot grant access the
    matrix withholds, so this page can never widen anyone's reach.

    ``position`` orders the modules on the mobile home hub, low first. A user
    in several groups sees the union of what those groups enable, at the
    earliest position any of them gives it — the same way the tab matrix
    combines groups.

    A group with no rows here is unconfigured and sees every module its tabs
    allow, so existing groups keep working until someone sets this up.
    """

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="mobile_modules"
    )
    module_key = models.CharField(
        max_length=50,
        help_text="Key from user.services.mobile_access.MOBILE_MODULES",
    )
    enabled = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Mobile module access"
        verbose_name_plural = "Mobile module access"
        unique_together = ("group", "module_key")
        ordering = ["position", "module_key"]

    def __str__(self):
        state = "on" if self.enabled else "off"
        return f"{self.group.name} · {self.module_key} ({state}, #{self.position})"


class GroupMobileTabPermission(models.Model):
    """Per-group actions for one *screen of the phone app*.

    The finer half of Mobile Access. ``GroupMobileAccess`` decides whether a
    module appears on the home hub at all; this decides what can be done inside
    it, screen by screen — the matrix an administrator actually sees.

    Only the 53 tabs with a phone screen behind them get rows here, and only
    four actions: ``save``/``update``/``favorite`` are already recorded in
    ``user.access.UNENFORCED_ACTIONS`` as ticks nothing reads, and there is no
    printing on a phone. Rendering a column that controls nothing is the one
    mistake this table exists to avoid repeating.

    Subtractive, like everything else on this page: an action is permitted only
    when the web matrix grants it *and* it is ticked here. A group with no rows
    is unconfigured and keeps whatever the web matrix allows.
    """

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="mobile_tab_permissions"
    )
    tab_code = models.CharField(
        max_length=100,
        help_text="Tab code from user.services.mobile_access.PHONE_SCREENS",
    )
    can_view = models.BooleanField(default=False)
    can_add = models.BooleanField(default=False)
    can_edit = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Mobile screen permission"
        verbose_name_plural = "Mobile screen permissions"
        unique_together = ("group", "tab_code")
        ordering = ["tab_code"]

    def __str__(self):
        on = [a for a in ("view", "add", "edit", "delete")
              if getattr(self, f"can_{a}")]
        return f"{self.group.name} · {self.tab_code} ({', '.join(on) or 'none'})"


class GroupDashboardWidget(models.Model):
    """Which dashboard widgets a group sees, and in what order.

    The widgets are already gated on the report tab each one links to, so this
    is a second, narrower switch: a group may be allowed to open the Stock
    Report and still not want its card on the dashboard. Both must agree — this
    can only take a widget away, never grant one the matrix withholds.

    ``position`` is the sort order within the row, low first. A user in several
    groups sees the union of what those groups enable, at the earliest position
    any of them gives it, which matches how the tab matrix combines groups.

    A group with no rows here is treated as unconfigured and sees every widget
    its tabs allow, so existing groups keep working until someone sets this up.
    """

    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="dashboard_widgets"
    )
    widget_key = models.CharField(
        max_length=50,
        help_text="Key from user.services.dashboard_widgets.WIDGETS",
    )
    enabled = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Dashboard widget access"
        verbose_name_plural = "Dashboard widget access"
        unique_together = ("group", "widget_key")
        ordering = ["position", "widget_key"]

    def __str__(self):
        state = "on" if self.enabled else "off"
        return f"{self.group.name} · {self.widget_key} ({state}, #{self.position})"
