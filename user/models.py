# user/models.py
from django.contrib.auth.models import Group, User
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    department = models.CharField(max_length=100, blank=True, null=True)
    role = models.CharField(max_length=100, blank=True, null=True)

    #: Take this person's tabs from their own matrix instead of their groups'.
    #: A switch rather than "are there rows", so an individual matrix saved with
    #: nothing ticked means nothing — see :class:`UserTabPermission`. Off by
    #: default, so no existing account changes until someone turns it on.
    individual_permissions = models.BooleanField(default=False)

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


class UserTabPermission(models.Model):
    """One person's own action permissions for one screen of the ERP.

    :class:`GroupTabPermission` answers "what may this *role* do", which is the
    right question until one person in a role needs something the rest of it
    does not. Giving them a group of their own works, and leaves a group per
    person behind for whoever inherits the system.

    So this is the per-person answer, and it **replaces** the group matrix
    rather than adding to or subtracting from it: an administrator who ticks
    four tabs here means those four, whatever the user's groups happen to say.
    One place answers "what may this person reach", which is the property that
    makes a permission auditable.

    Switched on per user by ``UserProfile.individual_permissions``, not by the
    presence of rows: a matrix deliberately saved with nothing ticked has no
    rows either, and falling back to the groups there would hand someone every
    tab their role has at the moment their access was meant to be removed. The
    same trap ``user_has_any_matrix_config`` documents for groups, one level in.

    Data scoping is a separate question with its own per-person answer — see
    :class:`EmployeeAccessProfile`. This decides which screens; that decides
    which rows.
    """

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="tab_permissions"
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
        unique_together = ("user", "tab_code")
        verbose_name = "User tab permission"

    def __str__(self):
        return f"{self.user.username} · {self.tab_code}"


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


class EmployeeAccessProfile(models.Model):
    """One employee's organizational data scope.

    :class:`GroupAccessProfile` answers "what may this *role* see", which is the
    right question until two people share a role and not a territory. Two branch
    managers are both Branch Managers; one runs Akbarpur and one runs Tulsipur,
    and no arrangement of groups says that without inventing a group per person.

    So this is the per-person answer, and where it exists it **replaces** the
    group scope rather than narrowing or widening it: an administrator who lists
    two branches here means those two, whatever the employee's groups happen to
    say. Permissions — which tabs, which actions — stay with the groups; this
    only decides which rows.

    Nothing changes for anyone until a profile is created, which is what makes
    it safe to add: an employee with no profile, or an inactive one, is scoped
    exactly as they are today.

    Each dimension has an ``all_*`` flag, defaulting True, so a half-filled
    profile is permissive rather than a lockout. Two of them mean "all *of what
    is already selected*" rather than "every row in the table": farms are all
    farms of the chosen branches, sheds all sheds of the chosen farms. That
    cascade is the whole point of the page — pick two branches and the farms and
    sheds beneath them follow without listing any of them.
    """

    ALL_BATCHES = "all"
    ACTIVE_BATCHES = "active"
    SELECTED_BATCHES = "selected"
    BATCH_VISIBILITY_CHOICES = [
        (ALL_BATCHES, "All Batches"),
        (ACTIVE_BATCHES, "Active Batches Only"),
        (SELECTED_BATCHES, "Selected Batches"),
    ]

    employee = models.OneToOneField(
        "hr.Employee", on_delete=models.CASCADE, related_name="access_profile",
        help_text="Whose scope this is. The login is reached through the "
                  "employee's user link.",
    )

    all_companies = models.BooleanField(default=True)
    companies = models.ManyToManyField(
        "account.CompanyProfile", blank=True, related_name="employee_profiles")

    all_branches = models.BooleanField(default=True)
    branches = models.ManyToManyField(
        "broiler.Branch", blank=True, related_name="employee_profiles")

    # All warehouses *of the selected branches*. Warehouse carries no branch
    # column — that was replaced by inventory.Mapping (TYPE_SECTOR_BRANCH,
    # from_id=warehouse, to_id=branch), the Office Mapping master — so the
    # cascade reads through there. A warehouse nobody has mapped belongs to no
    # branch and so falls outside a branch-derived scope.
    all_warehouses = models.BooleanField(default=True)
    warehouses = models.ManyToManyField(
        "inventory.Warehouse", blank=True, related_name="employee_profiles")

    # All farms *of the selected branches* — BroilerFarm.branch makes that real.
    all_farms = models.BooleanField(default=True)
    farms = models.ManyToManyField(
        "broiler.BroilerFarm", blank=True, related_name="employee_profiles")

    # All sheds *of the farms in scope*, likewise via BroilerFarmShed.farm.
    all_sheds = models.BooleanField(default=True)
    sheds = models.ManyToManyField(
        "broiler.BroilerFarmShed", blank=True, related_name="employee_profiles")

    all_cost_centres = models.BooleanField(default=True)
    cost_centres = models.ManyToManyField(
        "account.OrganizationCentre", blank=True, related_name="employee_profiles")

    batch_visibility = models.CharField(
        max_length=10, choices=BATCH_VISIBILITY_CHOICES, default=ALL_BATCHES,
        help_text="Active Batches Only hides settled flocks without naming any.",
    )
    batches = models.ManyToManyField(
        "broiler.BroilerBatch", blank=True, related_name="employee_profiles",
        help_text="Only read when batch visibility is 'Selected Batches'.")

    notes = models.CharField(max_length=250, blank=True)
    # Switched off rather than deleted, so a scope can be lifted for a week
    # without losing what it was. An inactive profile scopes nobody.
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="employee_access_profiles_updated")

    class Meta:
        verbose_name = "Employee Organization Access"
        verbose_name_plural = "Employee Organization Access"
        ordering = ["employee__full_name"]

    def __str__(self):
        return f"Organization access · {self.employee.full_name}"


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


class AppRelease(models.Model):
    """One published build of the phone app.

    The app is sideloaded, not distributed through a store, so there is no
    platform update mechanism behind it — this is that mechanism. The phone
    polls the latest row (by ``version_code``, Android's own integer) against
    its own installed version and offers or forces an update accordingly.

    ``apk_file`` is public: the file itself carries nothing sensitive, and a
    signed private-storage URL would only complicate a plain download link.
    """

    version = models.CharField(max_length=20, help_text="e.g. 0.2.1")
    version_code = models.PositiveIntegerField(
        unique=True, help_text="Android versionCode — must increase with every release")
    apk_file = models.FileField(upload_to="app-releases/")
    #: Blocks the app (no dismiss) until the user updates — for a release the
    #: old client cannot safely keep talking to the API on, e.g. a breaking
    #: change. Optional releases just show a dismissible banner.
    force_update = models.BooleanField(default=False)
    release_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version_code"]

    def __str__(self):
        return f"v{self.version} (code {self.version_code})"
