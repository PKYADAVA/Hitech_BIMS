# user/views.py
from collections import defaultdict
from datetime import datetime
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.db.models import Count
from django.contrib.auth.models import User
from django.utils.timezone import localtime
import datetime
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import Group, Permission
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin

from hr.models import Designation, Employee
from hr.models import Group as HrGroup
from inventory.models import Warehouse
from .models import UserProfile, GroupTabPermission, GroupAccessProfile
from .access import (MODULE_REGISTRY, ACTIONS, ALL_TAB_CODES,
                     UNENFORCED_ACTIONS, UNENFORCED_FLAGS)


from django.contrib.auth import login as auth_login, logout as auth_logout


def login(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)

        if user is not None:
            auth_login(request, user)
            return redirect(
                "dashboard"
            )  # Redirect to a dashboard or homepage after login
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, "login.html")


def logout(request):
    auth_logout(request)
    return redirect("login")


def _preview_group(request):
    """The group a Dashboard Access preview is being rendered for, if any.

    Rendering someone else's dashboard is a permission of its own: only a user
    who may open Dashboard Access can do it, and only ever read-only.
    """
    from .access import user_can

    raw = (request.GET.get("preview_group") or "").strip()
    if not raw.isdigit():
        return None
    if not user_can(getattr(request, "user", None), "dashboard_access", "view"):
        return None
    return Group.objects.filter(id=raw).first()


def _preview_prefs(request):
    """Unsaved switches from the editor, when it is previewing its own form.

    Present-but-empty is meaningful ("nothing enabled"), so absence is what
    falls back to the saved rows — not emptiness.
    """
    from .services.dashboard_widgets import parse_panel_override

    if "panels" not in request.GET or not _preview_group(request):
        return None
    return parse_panel_override(request.GET.get("panels"))


def _home_context(request):
    """Filter-option lists for the Field Team widget and the widget filter bar
    (cheap; harmless to compute even for users without access — both are
    permission-gated in the template)."""
    from broiler.models import BroilerFarm
    from .services.dashboard_widgets import dashboard_panels, withheld_panels
    from .services.scoping import branches_for, farms_for, supervisors_for

    user = getattr(request, "user", None)
    preview = _preview_group(request)
    panels = dashboard_panels(getattr(request, "user", None), as_group=preview,
                              prefs_override=_preview_prefs(request))
    # The widget grid sits wherever its earliest card sits, so ordering one
    # card to the top brings the row with it.
    card_positions = [v for k, v in panels.items()
                      if k not in ("quick_actions", "field_team")]

    return {
        "dash_panels": panels,
        "preview_group": preview,
        "preview_withheld": (withheld_panels(preview, _preview_prefs(request))
                             if preview else []),
        # The widget cards are fetched by JS, so the override has to travel to
        # that request too or the cards show the saved state while the
        # server-rendered panels show the live one.
        "preview_panels": (request.GET.get("panels")
                           if _preview_prefs(request) is not None else None),
        # Chrome off inside the preview iframe: it is a picture of the page, not
        # a place to navigate from.
        "preview_mode": bool(preview) and request.GET.get("preview") == "1",
        "dash_widgets_order": min(card_positions) if card_positions else 99,
        "trk_warehouses": Warehouse.objects.all().order_by("name"),
        "trk_groups": HrGroup.objects.all().order_by("name"),
        "trk_designations": Designation.objects.all().order_by("title"),
        # Scoped: a user limited to one branch is offered that branch only.
        "dash_branches": branches_for(user).order_by("branch_name"),
        # BroilerFarm.line is free text, not a foreign key, so the options are
        # the values actually in use — same source as the Day Record report,
        # which guarantees every option can match something. Taken from the
        # farms the user may see, so the line list narrows with them.
        "dash_lines": (farms_for(user).exclude(line="").order_by("line")
                       .values_list("line", flat=True).distinct()),
        "dash_supervisors": supervisors_for(user).order_by("name"),
        "dash_farms": farms_for(user).order_by("farm_name"),
    }


@login_required
def dashboard_access(request):
    """User > Dashboard Access — one row per group, with the usual actions.

    Only groups that have been configured appear here. A group with no row is
    unconfigured and sees whatever its tabs allow, which is how the system
    behaved before this page existed.
    """
    from .models import GroupDashboardWidget
    from .services.dashboard_widgets import all_panels

    titles = {key: title for key, title, *_ in all_panels()}
    total = len(titles)

    rows = []
    for group in Group.objects.order_by("name"):
        saved = list(GroupDashboardWidget.objects.filter(group=group))
        if not saved:
            continue
        on = [r for r in sorted(saved, key=lambda r: r.position) if r.enabled]
        rows.append({
            "group": group,
            "enabled_count": len(on),
            "total": total,
            "names": ", ".join(titles.get(r.widget_key, r.widget_key) for r in on) or "None",
        })

    return render(request, "dashboard_access_list.html", {
        "rows": rows,
        "unconfigured": Group.objects.exclude(
            id__in=[r["group"].id for r in rows]).order_by("name"),
    })


@login_required
def dashboard_access_form(request):
    """Add or edit one group's dashboard access."""
    from .models import GroupDashboardWidget
    from .services.dashboard_widgets import all_panels

    panels = list(all_panels())

    if request.method == "POST":
        group = get_object_or_404(Group, id=request.POST.get("group") or 0)
        GroupDashboardWidget.objects.filter(group=group).delete()
        GroupDashboardWidget.objects.bulk_create([
            GroupDashboardWidget(
                group=group, widget_key=key,
                enabled=request.POST.get(f"on_{key}") == "on",
                position=int((request.POST.get(f"pos_{key}") or "").strip() or 0))
            for key, _title, _tabs, _icon, _colour in panels
        ])
        messages.success(request, f"Dashboard access saved for “{group.name}”.")
        return redirect("dashboard_access")

    group_id = (request.GET.get("group") or "").strip()
    selected = Group.objects.filter(id=group_id).first() if group_id.isdigit() else None

    saved = {}
    if selected:
        saved = {r.widget_key: r for r in
                 GroupDashboardWidget.objects.filter(group=selected)}

    widgets = []
    for index, (key, title, tabs, icon, colour) in enumerate(panels):
        row = saved.get(key)
        widgets.append({
            "key": key, "title": title, "icon": icon, "colour": colour,
            "tabs": ", ".join(tabs),
            # A group being configured for the first time starts with everything
            # on, in registry order — the same as its current behaviour.
            "enabled": row.enabled if row else True,
            "position": row.position if row else index,
        })
    widgets.sort(key=lambda w: w["position"])

    return render(request, "dashboard_access_form.html", {
        "groups": Group.objects.order_by("name"),
        "selected_group": selected,
        "widgets": widgets,
        "editing": bool(saved),
    })


@login_required
def dashboard_access_preview(request, group_id):
    """What this group's dashboard would look like — JSON for the modal.

    Computed for the group rather than by impersonating a member, and it says
    *why* a panel is missing: switched off here, or not permitted by the tab
    matrix at all.
    """
    from .services.dashboard_widgets import panels_for_group

    group = get_object_or_404(Group, id=group_id)
    return JsonResponse({"group": group.name,
                         "panels": panels_for_group(group)})


@login_required
def dashboard_access_delete(request, group_id):
    """Clear a group's dashboard access, returning it to the default."""
    from .models import GroupDashboardWidget

    group = get_object_or_404(Group, id=group_id)
    GroupDashboardWidget.objects.filter(group=group).delete()
    messages.success(
        request,
        f"Dashboard access cleared for “{group.name}” — it now sees every "
        "widget its permissions allow.")
    return redirect("dashboard_access")


@login_required
def master_import(request, tab_code):
    """Import a spreadsheet into a master, from the master's own page.

    Gated on the tab's *add* right, not on is_superuser: the people who
    maintain a master are the ones who should be able to load it, and the
    matrix already says who they are.

    GET returns the column template. POST validates; it only writes when
    ``commit`` is set, so a bad file is a list of row errors rather than a
    half-imported master.
    """
    from django.http import HttpResponse

    from .access import user_can
    from .services.bulk_import import IMPORTABLE, run_import, template_columns

    if tab_code not in IMPORTABLE:
        return JsonResponse({"error": "This page does not support import."}, status=404)
    if not user_can(request.user, tab_code, "add"):
        return JsonResponse(
            {"error": "You do not have permission to import into this page."},
            status=403)

    columns = template_columns(tab_code)

    if request.method == "GET":
        if request.GET.get("template") == "csv":
            header = ",".join(columns) + "\r\n"
            response = HttpResponse(header, content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="{tab_code}_import_template.csv"')
            return response
        return JsonResponse({"columns": columns})

    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "Choose a file to import."}, status=400)

    commit = request.POST.get("commit") == "1"
    result, errors = run_import(tab_code, upload, upload.name, commit=commit)
    if result is None:
        return JsonResponse({"errors": [{"row": r, "message": m} for r, m in errors]},
                            status=400)

    totals = result.totals if hasattr(result, "totals") else {}
    return JsonResponse({
        "committed": commit,
        "rows": len(result.rows),
        "new": totals.get("new", 0),
        "updated": totals.get("update", 0),
        "skipped": totals.get("skip", 0),
        "invalid": totals.get("invalid", 0) + totals.get("error", 0),
        "errors": [{"row": r, "message": m} for r, m in errors[:50]],
        "more_errors": max(0, len(errors) - 50),
    })


@login_required
def global_search_api(request):
    """Dashboard search box — pages and master records in one response.

    The permission filtering lives in the service, keyed on the same tab codes
    the nav and the view-guard use, so a hit can never point somewhere the user
    would be bounced out of.
    """
    from .services.global_search import global_search

    return JsonResponse(global_search(request.user, request.GET.get("q", "")))


@login_required
def dashboard_widgets_api(request):
    """Dashboard widget data, fetched after the page paints.

    The dashboard is the most-loaded page in the ERP and some of these figures
    walk every supplier and customer, so the shell renders immediately and the
    numbers arrive here rather than blocking the first paint.
    """
    from .services.dashboard_widgets import dashboard_widgets, parse_filters

    filters = parse_filters(request.GET)
    return JsonResponse({"widgets": dashboard_widgets(
        request.user, filters, as_group=_preview_group(request),
        prefs_override=_preview_prefs(request))})


# X_FRAME_OPTIONS is DENY site-wide. The Dashboard Access preview frames this
# page from the same origin, so relax it here only — external sites still
# cannot frame the dashboard.
def _dashboard_or_landing(request):
    """The dashboard, or the first page they can open if it is switched off.

    Not enforced through the middleware: its denial redirects *to* home, so
    refusing home there would loop. If there is nowhere else to send them the
    dashboard still renders — an empty page beats a redirect cycle.
    """
    from .access import first_landing_url, user_sees_dashboard

    if not user_sees_dashboard(request.user):
        landing = first_landing_url(request.user)
        if landing and landing != request.path:
            return redirect(landing)
    return render(request, "home.html", _home_context(request))


@xframe_options_sameorigin
def dashboard(request):
    return _dashboard_or_landing(request)


def home(request):
    return _dashboard_or_landing(request)


def forgot_password_view(request):
    if request.method == "POST":
        # Implement password reset logic here
        email = request.POST.get("email")
        # Example: Send reset link or code to the user's email
        # (This part requires email configuration in Django)
        return JsonResponse(
            {"message": "Password reset instructions sent to your email."}
        )
    return render(request, "forget_password.html")


@login_required
def user_profile(request):
    """Save the signed-in user's own profile.

    The profile is a modal in the top navbar (see main_top_navbar.html), so this
    is a POST endpoint. A GET is someone following an old link to the page the
    modal replaced — send them home rather than serve a second, stale copy of
    the same form.
    """
    if request.method != "POST":
        return redirect("/")

    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    email = request.POST.get("email", "").strip()

    if not first_name or not email:
        return JsonResponse({"error": "First name and email are required."}, status=400)

    user = request.user
    user.first_name = first_name
    user.last_name = last_name
    user.email = email
    user.save()
    return JsonResponse({"message": "Profile updated successfully."})


@login_required
def update_password(request):
    if request.method == "POST":
        old_password = request.POST.get("old_password")
        new_password = request.POST.get("new_password")
        confirm_password = request.POST.get("confirm_password")
        user = request.user

        if not user.check_password(old_password):
            return JsonResponse({"error": "Incorrect password."})

        if new_password != confirm_password:
            return JsonResponse({"error": "Passwords do not match."})

        user.set_password(new_password)
        user.save()
        return JsonResponse({"message": "Password updated successfully."})

    return render(request, "update_password.html")


@login_required
def create_user(request):
    context = {
        "users": User.objects.all().order_by("username"),
        # Only employees not yet linked to a user can be attached to a new account.
        "employees": Employee.objects.filter(user__isnull=True).all(),
        "groups": Group.objects.all(),
    }

    if request.method == "POST":
        employee_id = request.POST.get("employee")
        username = request.POST.get("username")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        group_id = request.POST.get("group")
        is_superuser = request.POST.get("is_superuser", "off") == "on"

        if password != confirm_password:
            return JsonResponse({"error": "Passwords do not match"}, status=400)

        # Save the user logic (example)
        try:
            user = User.objects.create_user(
                username=username,
                password=password,
                is_superuser=is_superuser,
            )
            if group_id:
                user.groups.add(group_id)
            user.save()

            # Linking an employee is optional — a user does not have to be an
            # employee to use the ERP.
            if employee_id:
                emp_obj = Employee.objects.get(id=employee_id)
                emp_obj.user = user
                emp_obj.save()

            return render(request, "create_user.html", context)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return render(request, "create_user.html", context)


@login_required
def update_user(request, user_id):
    user = get_object_or_404(User, id=user_id)

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        group_id = request.POST.get("group")
        is_superuser = request.POST.get("is_superuser", "off") == "on"

        if User.objects.filter(username=username).exclude(id=user.id).exists():
            return JsonResponse({"error": "Username already exists."}, status=400)

        if password or confirm_password:
            if password != confirm_password:
                return JsonResponse({"error": "Passwords do not match."}, status=400)
            user.set_password(password)

        user.username = username
        user.is_superuser = is_superuser
        user.save()

        user.groups.clear()
        if group_id:
            user.groups.add(group_id)

        return JsonResponse({"message": "User updated successfully."})

    return JsonResponse({"error": "Invalid request method."}, status=405)


@login_required
def assign_groups(request):
    if request.method == "POST":
        user = get_object_or_404(User, id=request.POST.get("user"))
        selected_groups = request.POST.getlist("groups[]")

        user.groups.clear()
        for group_id in selected_groups:
            user.groups.add(Group.objects.get(id=group_id))

        return JsonResponse(
            {
                "message": "Groups updated successfully.",
                "updated_groups_html": "".join(
                    f"<span class='badge bg-info text-dark px-2 py-1'>{g.name}</span> "
                    for g in user.groups.all()
                ),
            }
        )
    context = {"users": User.objects.all(), "groups": Group.objects.all()}

    return render(request, "assign_permission.html", context)


@login_required
def manage_groups(request):
    """Create/edit a user group AND define its Web-Access permission matrix in a
    single page. A group's permissions are the matrix defined here."""
    if request.method == "POST":
        group_id = request.POST.get("group")
        group_name = (request.POST.get("name") or "").strip()

        if group_id:
            group = get_object_or_404(Group, id=group_id)
            if group_name and group_name != group.name:
                if Group.objects.filter(name=group_name).exclude(id=group.id).exists():
                    messages.error(request, f"A group named '{group_name}' already exists.")
                    return redirect(f"{reverse('user_groups')}?group={group.id}#webaccess")
                group.name = group_name
                group.save()
        elif group_name:
            group, _created = Group.objects.get_or_create(name=group_name)
        else:
            messages.error(request, "Group name is required.")
            return redirect("user_groups")

        return _persist_web_access(request, group)

    # GET: list of groups + the Web-Access editor for the selected group.
    groups = Group.objects.all().order_by("name")
    groups_with_permissions = []
    for group in groups:
        tab_count = group.tab_permissions.count()
        groups_with_permissions.append(
            {"name": group.name, "id": group.id, "tab_count": tab_count}
        )

    context = {
        "groups": groups,
        "groups_with_permissions": groups_with_permissions,
        "creating": request.GET.get("new") == "1",
    }
    context.update(build_web_access_context(request.GET.get("group")))
    # Four of the eight columns were decorative; Print is now enforced on
    # exports, and the editor says which of the rest still are.
    context["unenforced_actions"] = UNENFORCED_ACTIONS
    context["unenforced_flags"] = UNENFORCED_FLAGS
    return render(request, "manage_groups.html", context)


@login_required
def get_assigned_groups(request):
    user_id = request.GET.get("user_id")
    user = get_object_or_404(User, id=user_id)
    assigned_groups = list(user.groups.values_list("id", flat=True))
    all_groups = list(Group.objects.values("id", "name"))

    return JsonResponse({"groups": assigned_groups, "all_groups": all_groups})


@login_required
def delete_group(request):
    if request.method == "POST":
        group_id = request.POST.get("group_id")

        try:
            group = Group.objects.get(id=group_id)
            group.delete()
            return JsonResponse({"message": "Group deleted successfully."})

        except Group.DoesNotExist:
            return JsonResponse({"error": "Group not found."}, status=400)


def _persist_web_access(request, group):
    """Persist the Web-Access matrix + data scoping for *group*. Returns a
    redirect back to the Manage-User-Groups page with the group pre-selected."""
    # --- Permission matrix ---------------------------------------------------
    for tab_code in ALL_TAB_CODES:
        values = {
            f"can_{action}": (request.POST.get(f"perm_{tab_code}_{action}") == "on")
            for action in ACTIONS
        }
        if any(values.values()):
            GroupTabPermission.objects.update_or_create(
                group=group, tab_code=tab_code, defaults=values
            )
        else:
            # Nothing ticked for this tab -> remove any stale row.
            GroupTabPermission.objects.filter(group=group, tab_code=tab_code).delete()

    # --- Access profile + data scoping ---------------------------------------
    profile, _ = GroupAccessProfile.objects.get_or_create(group=group)
    profile.is_superuser = request.POST.get("is_superuser") == "on"
    profile.access_type = request.POST.get("access_type", "sub_admin")
    profile.login_type = request.POST.get("login_type", "password")
    profile.sale_multiple_edit = request.POST.get("sale_multiple_edit") == "yes"
    profile.sale_multiple_delete = request.POST.get("sale_multiple_delete") == "yes"
    profile.dashboard = request.POST.get("dashboard", "yes") == "yes"

    scope_fields = ["branches", "lines", "farms", "sectors",
                    "customer_groups", "supplier_groups"]
    for field in scope_fields:
        setattr(profile, f"all_{field}", request.POST.get(f"all_{field}") == "on")
    profile.save()

    for field in scope_fields:
        getattr(profile, field).set(request.POST.getlist(f"{field}[]"))

    messages.success(request, f"Web access saved for group '{group.name}'.")
    return redirect(f"{reverse('user_groups')}?group={group.id}#webaccess")


def build_web_access_context(selected_id):
    """Build the Web-Access matrix + scoping context for a selected group id
    (or an empty/defaults context when none is selected)."""
    from broiler.models import Branch, BroilerLine, BroilerFarm
    from inventory.models import Warehouse
    from sales.models import CustomerGroup
    from purchase.models import VendorGroup

    selected_group = None
    saved_perms = {}
    profile = None
    if selected_id:
        selected_group = get_object_or_404(Group, id=selected_id)
        for tp in selected_group.tab_permissions.all():
            saved_perms[tp.tab_code] = {a: getattr(tp, f"can_{a}") for a in ACTIONS}
        profile = getattr(selected_group, "access_profile", None)

    def _scope(field):
        if profile is None:
            return set()
        return set(getattr(profile, field).values_list("id", flat=True))

    # Pre-compute checked state per tab so the template only iterates. The matrix
    # follows the navbar: module (category row) -> section (Master/Transactions/
    # Reports, module row) -> tabs. `cid`/`mid` are stable ids for the header/row
    # "select all" toggles in the template.
    matrix = []
    for ci, module in enumerate(MODULE_REGISTRY):
        sections = []
        for si, section in enumerate(module["sections"]):
            mid = f"{ci}-{si}"
            tabs = []
            for tab in section["tabs"]:
                code, label = tab[0], tab[1]
                perms = saved_perms.get(code, {})
                tabs.append(
                    {
                        "code": code,
                        "label": label,
                        "cells": [
                            {"action": a, "checked": perms.get(a, False)}
                            for a in ACTIONS
                        ],
                    }
                )
            sections.append({"label": section["label"], "mid": mid, "tabs": tabs})
        matrix.append(
            {"category": module["label"], "cid": str(ci), "modules": sections}
        )

    def _all_flag(flag):
        # Default to True (unrestricted) when no profile has been saved yet.
        return getattr(profile, flag) if profile else True

    def _opts(queryset, label_attr):
        return [
            {"id": obj.id, "label": getattr(obj, label_attr) or f"#{obj.id}"}
            for obj in queryset
        ]

    scopes = [
        {"label": "Branch", "field": "branches", "all": _all_flag("all_branches"),
         "options": _opts(Branch.objects.all(), "branch_name"),
         "selected": _scope("branches")},
        {"label": "Line", "field": "lines", "all": _all_flag("all_lines"),
         "options": _opts(BroilerLine.objects.all(), "description"),
         "selected": _scope("lines")},
        {"label": "Farm", "field": "farms", "all": _all_flag("all_farms"),
         "options": _opts(BroilerFarm.objects.all(), "farm_name"),
         "selected": _scope("farms")},
        {"label": "Sector", "field": "sectors", "all": _all_flag("all_sectors"),
         "options": _opts(Warehouse.objects.all(), "name"),
         "selected": _scope("sectors")},
        {"label": "Customer Group Access", "field": "customer_groups",
         "all": _all_flag("all_customer_groups"),
         "options": _opts(CustomerGroup.objects.all(), "code"),
         "selected": _scope("customer_groups")},
        {"label": "Supplier Group Access", "field": "supplier_groups",
         "all": _all_flag("all_supplier_groups"),
         "options": _opts(VendorGroup.objects.all(), "code"),
         "selected": _scope("supplier_groups")},
    ]

    return {
        "matrix": matrix,
        "actions": ACTIONS,
        "wa_selected_group": selected_group,
        "profile": profile,
        "scopes": scopes,
    }


@login_required
def user_analytics(request):
    return render(request, "user_analytics.html")


def user_analytics_data(request):
    """Return analytics data as JSON for jQuery AJAX"""

    # User Registrations Per Day (Last 30 Days)
    today = localtime().date()
    past_30_days = today - datetime.timedelta(days=30)

    registrations = (
        User.objects.filter(date_joined__date__gte=past_30_days)
        .extra(select={"day": "date(date_joined)"})
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    registration_dates = [r["day"].strftime("%Y-%m-%d") for r in registrations]
    registration_counts = [r["count"] for r in registrations]

    # User Role Distribution
    roles = {
        "Regular Users": User.objects.filter(
            is_staff=False, is_superuser=False
        ).count(),
        "Staff Users": User.objects.filter(is_staff=True, is_superuser=False).count(),
        "Super Admins": User.objects.filter(is_superuser=True).count(),
    }

    role_labels = list(roles.keys())
    role_counts = list(roles.values())

    # Users Per Group
    groups = Group.objects.annotate(user_count=Count("user"))
    group_labels = [g.name for g in groups]
    group_counts = [g.user_count for g in groups]

    # Last Login Data
    users = User.objects.all().values(
        "id", "username", "email", "last_login", "is_active"
    )
    user_data = []
    for user in users:
        last_login = (
            localtime(user["last_login"]).strftime("%b %d, %Y, %I:%M %p")
            if user["last_login"]
            else "Never"
        )
        user_data.append(
            {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "last_login": last_login,
                "status": "Active" if user["is_active"] else "Inactive",
            }
        )

    return JsonResponse(
        {
            "registration_dates": registration_dates,
            "registration_counts": registration_counts,
            "role_labels": role_labels,
            "role_counts": role_counts,
            "group_labels": group_labels,
            "group_counts": group_counts,
            "users": user_data,
        }
    )
