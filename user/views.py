# user/views.py
from collections import defaultdict
from datetime import datetime
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.db import transaction
from django.db.models import Count, ProtectedError
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
                     UNENFORCED_ACTIONS, UNENFORCED_FLAGS, iter_tabs)


from django.contrib.auth import login as auth_login, logout as auth_logout


def login(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)

        if user is not None:
            auth_login(request, user)
            # "Remember Me", honoured rather than decorative: unchecked, the
            # session dies with the browser, which is what a supervisor on a
            # shared office machine is asking for when they clear it.
            if not request.POST.get("remember"):
                request.session.set_expiry(0)
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
def mobile_access(request):
    """User > Mobile Access — one row per configured group.

    Only groups that have been configured appear. A group with no row is
    unconfigured and gets every module its tabs allow, which is how the phone
    behaved before this page existed.
    """
    from .models import GroupMobileAccess, GroupMobileTabPermission
    from .services.mobile_access import (GOVERNED_TABS, all_modules,
                                         superuser_only_members)

    titles = {key: title for key, title, *_ in all_modules()}
    total = len(titles)

    rows = []
    for group in Group.objects.order_by("name"):
        saved = list(GroupMobileAccess.objects.filter(group=group))
        screens = list(GroupMobileTabPermission.objects.filter(group=group))
        if not saved and not screens:
            continue
        on = [r for r in sorted(saved, key=lambda r: r.position) if r.enabled]
        members, supers = superuser_only_members(group)
        rows.append({
            "group": group,
            "enabled_count": len(on),
            "total": total,
            "names": ", ".join(titles.get(r.module_key, r.module_key) for r in on) or "None",
            "screens_on": sum(1 for r in screens if r.can_view),
            "screens_total": len(GOVERNED_TABS),
            # A group of nothing but superusers is configured and inert.
            "inert": bool(members) and members == supers,
        })

    return render(request, "mobile_access_list.html", {
        "rows": rows,
        "unconfigured": Group.objects.exclude(
            id__in=[r["group"].id for r in rows]).order_by("name"),
    })


@login_required
def mobile_access_form(request):
    """Add or edit one group's mobile access — the screen × action matrix.

    Two levels on one page: a module row that shows or hides a whole hub tile
    and sets its order, and under it a row per phone screen with View / Add /
    Edit / Delete. Only the 53 tabs with a screen behind them are listed; the
    other 89 web tabs would be ticks that control nothing.
    """
    from .models import GroupMobileAccess, GroupMobileTabPermission
    from .services.mobile_access import (MOBILE_ACTIONS, all_modules,
                                         group_screen_perms, screens_by_module,
                                         screen_tree, superuser_only_members,
                                         unbuilt_by_module)

    modules = all_modules()
    sections = screens_by_module()

    if request.method == "POST":
        group = get_object_or_404(Group, id=request.POST.get("group") or 0)

        # The form's answer, independent of which group it is written to, so
        # applying it to several is the same operation run more than once
        # rather than a second code path that can drift from the first.
        module_state = {
            key: {"enabled": request.POST.get(f"on_{key}") == "on",
                  "position": int((request.POST.get(f"pos_{key}") or "").strip() or 0)}
            for key, *_rest in modules
        }
        screen_state = {}
        for _key, _title, screens in sections:
            for screen in screens:
                # Only the actions the row actually offers; a report's Add/
                # Edit/Delete are never posted, and must not be read as "off".
                screen_state[screen["tab"]] = {
                    a: (a in screen["actions"]
                        and request.POST.get(f"p_{screen['tab']}_{a}") == "on")
                    for a in MOBILE_ACTIONS
                }

        also = Group.objects.filter(id__in=request.POST.getlist("also")).exclude(
            id=group.id)
        targets = [group, *also]

        for target in targets:
            _write_mobile_access(target, module_state, screen_state)

        if also:
            names = ", ".join(g.name for g in also)
            messages.success(
                request,
                f"Mobile access saved for “{group.name}” and applied to {names}.")
        else:
            messages.success(request, f"Mobile access saved for “{group.name}”.")
        return redirect("mobile_access")

    group_id = (request.GET.get("group") or "").strip()
    selected = Group.objects.filter(id=group_id).first() if group_id.isdigit() else None

    saved_modules, saved_screens, members, supers = {}, None, 0, 0
    if selected:
        saved_modules = {r.module_key: r for r in
                         GroupMobileAccess.objects.filter(group=selected)}
        saved_screens = group_screen_perms(selected)
        members, supers = superuser_only_members(selected)

    # "Copy from" fills the form with another group's configuration without
    # saving anything, so it can be reviewed and adjusted against *this*
    # group's web permissions before it is committed. Anything the target
    # cannot reach renders disabled and is dropped on save — copying can no
    # more grant access than editing can.
    copy_id = (request.GET.get("copy_from") or "").strip()
    copied_from = (Group.objects.filter(id=copy_id).exclude(id=selected.id).first()
                   if selected and copy_id.isdigit() else None)
    if copied_from:
        source_modules = {r.module_key: r for r in
                          GroupMobileAccess.objects.filter(group=copied_from)}
        if source_modules:
            saved_modules = source_modules
        saved_screens = group_screen_perms(copied_from)

    # What the web matrix grants, so the editor can mark a screen the group
    # cannot reach at all — ticking it there would change nothing.
    web = _group_web_actions(selected) if selected else {}

    unbuilt = unbuilt_by_module()
    tree = {key: groups for key, _title, groups in screen_tree()}

    blocks = []
    for index, (key, title, nav, icon, colour) in enumerate(modules):
        row = saved_modules.get(key)
        groups = []
        for gi, (section_label, screens) in enumerate(tree.get(key, [])):
            rows = _screen_rows(screens, web, saved_screens, MOBILE_ACTIONS)
            groups.append({"label": section_label, "sid": f"{index}-{gi}",
                           "screens": rows})

        # Web tabs of this module the app has no screen for. Marked when the
        # group holds them, since "I granted this and it isn't here" is the
        # question these rows exist to answer.
        pending = [{**item, "granted": bool(web.get(item["tab"]))}
                   for item in unbuilt.get(key, [])]

        blocks.append({
            "key": key, "title": title, "nav": nav, "icon": icon, "colour": colour,
            "enabled": row.enabled if row else True,
            "position": row.position if row else index,
            "sections": groups,
            "screen_count": sum(len(g["screens"]) for g in groups),
            "unbuilt": pending,
            "unbuilt_granted": sum(1 for p in pending if p["granted"]),
        })
    blocks.sort(key=lambda b: b["position"])

    return render(request, "mobile_access_form.html", {
        "groups": Group.objects.order_by("name"),
        "selected_group": selected,
        "blocks": blocks,
        "actions": MOBILE_ACTIONS,
        "editing": bool(saved_modules or saved_screens),
        "members": members,
        "superusers": supers,
        "copied_from": copied_from,
        "other_groups": (Group.objects.exclude(id=selected.id).order_by("name")
                         if selected else Group.objects.none()),
    })


def _write_mobile_access(group, module_state, screen_state):
    """Write one form's answer to one group.

    Applying a configuration to several groups is this called several times,
    so the shortcut and a single save go through exactly the same write.
    """
    from .models import GroupMobileAccess, GroupMobileTabPermission
    from .services.mobile_access import MOBILE_ACTIONS

    GroupMobileAccess.objects.filter(group=group).delete()
    GroupMobileAccess.objects.bulk_create([
        GroupMobileAccess(group=group, module_key=key,
                          enabled=state["enabled"], position=state["position"])
        for key, state in module_state.items()
    ])

    GroupMobileTabPermission.objects.filter(group=group).delete()
    GroupMobileTabPermission.objects.bulk_create([
        GroupMobileTabPermission(group=group, tab_code=tab,
                                 **{f"can_{a}": ticks[a] for a in MOBILE_ACTIONS})
        for tab, ticks in screen_state.items()
    ])



def _screen_rows(screens, web, saved, actions):
    """Render-ready rows for one section of the Mobile Access tree.

    A group being configured for the first time starts with exactly what the
    web matrix already allows, so saving changes nothing until someone unticks
    something — which is what "unconfigured" means everywhere else here.
    """
    rows = []
    for screen in screens:
        granted = web.get(screen["tab"], {})
        current = (saved or {}).get(screen["tab"])
        applicable = screen["actions"]
        rows.append({
            **screen,
            # A report has one meaningful action; the other three columns
            # render as "n/a" rather than as boxes that decide nothing.
            "actions": [{
                "name": action,
                "applies": action in applicable,
                # ANDed with `granted` so a tick the web matrix no longer allows
                # shows as off rather than as checked-and-disabled. It is not in
                # effect either way — a disabled box does not even submit — and
                # showing it ticked claims access the group does not have.
                "on": action in applicable and granted.get(action, False) and (
                    current[action] if current is not None else True),
                "granted": action in applicable and granted.get(action, False),
            } for action in actions],
            "reachable": any(granted.get(a) for a in applicable),
        })
    return rows


def _group_web_actions(group):
    """``{tab_code: {action: bool}}`` the web matrix grants this group.

    Mirrors the matrix's own rules rather than reading rows naively: a group
    with no rows at all is unrestricted, and an ``admin`` access type bypasses
    everything — the same two exceptions ``user_can`` makes. Without them the
    editor would grey out screens the group really can reach.
    """
    from .access import ACTIONS, ALL_TAB_CODES
    from .models import GroupAccessProfile, GroupTabPermission
    from .services.mobile_access import MOBILE_ACTIONS

    rows = list(GroupTabPermission.objects.filter(group=group))
    profile = GroupAccessProfile.objects.filter(group=group).first()
    unrestricted = (not rows) or (profile and profile.access_type == "admin")
    if unrestricted:
        return {tab: {a: True for a in MOBILE_ACTIONS} for tab in ALL_TAB_CODES}

    out = {}
    for row in rows:
        # "View" means any action here, exactly as user_can treats it.
        any_action = any(getattr(row, f"can_{a}", False) for a in ACTIONS)
        out[row.tab_code] = {
            "view": any_action,
            "add": row.can_add,
            "edit": row.can_edit,
            "delete": row.can_delete,
        }
    return out


@login_required
def mobile_access_preview(request, group_id):
    """What this group's phone home hub would show — JSON for the modal.

    Says *why* a module is missing: switched off here, or not permitted by the
    tab matrix at all.
    """
    from .services.mobile_access import modules_for_group

    group = get_object_or_404(Group, id=group_id)

    # ``modules`` is optional: the list page omits it and gets the saved state,
    # the editor passes its live switches as "key:pos,key:pos" so the preview
    # matches the form. An empty string is meaningful — nothing enabled.
    raw = request.GET.get("modules")
    override = None
    if raw is not None:
        override = {}
        for chunk in raw.split(","):
            key, _, pos = chunk.partition(":")
            key = key.strip()
            if key:
                override[key] = int(pos) if pos.strip().isdigit() else 0

    return JsonResponse({"group": group.name,
                         "modules": modules_for_group(group, override)})


@login_required
def mobile_access_delete(request, group_id):
    """Clear a group's mobile access, returning it to the default."""
    from .models import GroupMobileAccess

    group = get_object_or_404(Group, id=group_id)
    GroupMobileAccess.objects.filter(group=group).delete()
    messages.success(
        request,
        f"Mobile access cleared for “{group.name}” — it now sees every "
        "module its permissions allow.")
    return redirect("mobile_access")


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


def _user_page_context():
    """Rebuilt per render, not per request: after creating a user the page has
    to show them, and the free-employee list has to have lost the one just
    attached."""
    return {
        "users": User.objects.select_related("employee").order_by("username"),
        # Only employees not yet linked to a user can be attached to a new account.
        "employees": Employee.objects.filter(user__isnull=True),
        # Every employee, for the edit dialog: it has to offer the free ones
        # *and* the one this user already has, which is not free by definition.
        # Each option carries its current user so the dialog can tell them apart.
        "all_employees": Employee.objects.select_related("user").order_by("full_name"),
        "groups": Group.objects.all(),
    }


@login_required
def create_user(request):

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

            # Rebuilt after the write, so the new account is on the list and
            # the employee just linked is no longer offered as free.
            return render(request, "create_user.html", _user_page_context())
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)

    return render(request, "create_user.html", _user_page_context())


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

        employee_id = (request.POST.get("employee") or "").strip()
        current = getattr(user, "employee", None)

        # Employee.user is one-to-one, so re-pointing it at someone else's
        # employee would silently unlink them. Refused instead, before anything
        # is written.
        if employee_id:
            chosen = Employee.objects.filter(id=employee_id).first()
            if not chosen:
                return JsonResponse({"error": "That employee no longer exists."},
                                    status=400)
            if chosen.user_id and chosen.user_id != user.id:
                return JsonResponse(
                    {"error": "%s is already linked to user %s."
                              % (chosen.full_name, chosen.user.username)},
                    status=400)

        user.username = username
        user.is_superuser = is_superuser
        user.save()

        user.groups.clear()
        if group_id:
            user.groups.add(group_id)

        # Detach first, so moving a user from one employee to another does not
        # leave both pointing at them.
        if current and str(current.id) != employee_id:
            current.user = None
            current.save(update_fields=["user"])
        if employee_id and (not current or str(current.id) != employee_id):
            chosen.user = user
            chosen.save(update_fields=["user"])

        return JsonResponse({"message": "User updated successfully."})

    return JsonResponse({"error": "Invalid request method."}, status=405)


def _last_active_superuser(user):
    """True when switching this account off would leave nobody who can switch
    it back on. The one state the Users page must not be able to reach."""
    if not (user.is_superuser and user.is_active):
        return False
    return not (User.objects.filter(is_superuser=True, is_active=True)
                .exclude(id=user.id).exists())


@login_required
def toggle_user_active(request, user_id):
    """Switch an account on or off.

    The everyday answer to "this person has left": Django refuses a login for
    an inactive user, so access stops at once, while everything they entered
    keeps its author. Deleting is for an account raised in error.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=405)

    user = get_object_or_404(User, id=user_id)
    if user.id == request.user.id:
        return JsonResponse(
            {"error": "You cannot deactivate the account you are signed in with."},
            status=400)
    if user.is_active and _last_active_superuser(user):
        return JsonResponse(
            {"error": "%s is the only active superuser. Promote someone else "
                      "first, or nobody can undo this." % user.username},
            status=400)

    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    return JsonResponse({
        "is_active": user.is_active,
        "message": "%s is now %s." % (user.username,
                                      "active" if user.is_active else "inactive"),
    })


@login_required
def delete_user(request, user_id):
    """Remove an account outright.

    Refused where the record would take something with it that is not the
    user's own: a change request names who raised and who reviewed it, and
    those columns are PROTECTed precisely so an approval trail cannot lose its
    author. Deactivating is offered instead, which is what is wanted in almost
    every case anyway.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=405)

    user = get_object_or_404(User, id=user_id)
    if user.id == request.user.id:
        return JsonResponse(
            {"error": "You cannot delete the account you are signed in with."},
            status=400)
    if _last_active_superuser(user):
        return JsonResponse(
            {"error": "%s is the only active superuser. Promote someone else "
                      "first." % user.username},
            status=400)

    username = user.username
    try:
        with transaction.atomic():
            user.delete()
    except ProtectedError:
        return JsonResponse(
            {"error": "%s has approval history against their name and cannot be "
                      "deleted without it. Deactivate the account instead — they "
                      "lose access and the trail keeps its author." % username},
            status=400)
    # The linked employee survives: Employee.user is SET_NULL, so the person
    # stays on the HR master and can be given a new account.
    return JsonResponse({"message": "%s deleted." % username})


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



# ---------------------------------------------------------------------------
# Per-user permissions
# ---------------------------------------------------------------------------

def _permission_matrix(saved_perms):
    """The Web-Access grid, given whatever rows answer for the subject.

    The same shape ``build_web_access_context`` builds for a group, so a user's
    matrix and a group's are the same grid in the same order — one of them
    quietly listing different tabs is exactly the confusion this page exists to
    remove.
    """
    matrix = []
    for ci, module in enumerate(MODULE_REGISTRY):
        sections = []
        for si, section in enumerate(module["sections"]):
            tabs = []
            for tab in section["tabs"]:
                code, label = tab[0], tab[1]
                perms = saved_perms.get(code, {})
                tabs.append({
                    "code": code, "label": label,
                    "cells": [{"action": a, "checked": perms.get(a, False)}
                              for a in ACTIONS],
                })
            sections.append({"label": section["label"], "mid": f"{ci}-{si}",
                             "tabs": tabs})
        matrix.append({"category": module["label"], "cid": str(ci),
                       "modules": sections})
    return matrix


@login_required
def user_permissions(request, user_id):
    """User > Users > Permissions — one person's own tab matrix.

    Groups answer "what may this role do", which is right until one person in a
    role needs something the rest of it does not. Giving them a group of their
    own works and leaves a group per person behind for whoever inherits the
    system, so this is the per-person answer instead.

    Switched on per user: while the switch is off nothing here applies and the
    groups answer exactly as they do today, which is what makes the page safe to
    open on an existing account.
    """
    from .models import UserProfile, UserTabPermission

    subject = get_object_or_404(User, id=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=subject)

    if request.method == "POST":
        individual = request.POST.get("individual_permissions") == "on"
        with transaction.atomic():
            profile.individual_permissions = individual
            profile.save(update_fields=["individual_permissions"])

            # Rewritten wholesale rather than merged: the form posts the whole
            # grid, so a cleared tick has to become a missing row.
            UserTabPermission.objects.filter(user=subject).delete()
            rows = []
            for code in ALL_TAB_CODES:
                values = {f"can_{a}": request.POST.get(f"perm_{code}_{a}") == "on"
                          for a in ACTIONS}
                if any(values.values()):
                    rows.append(UserTabPermission(user=subject, tab_code=code, **values))
            UserTabPermission.objects.bulk_create(rows)

        messages.success(
            request,
            "Permissions saved for %s — %s."
            % (subject.username,
               "their own matrix now applies" if individual
               else "their groups still apply, this matrix is switched off"))
        return redirect(reverse('create_user_permissions', args=[subject.id]))

    saved = {tp.tab_code: {a: getattr(tp, f"can_{a}") for a in ACTIONS}
             for tp in UserTabPermission.objects.filter(user=subject)}
    # What the groups grant today, so the page can say what turning the switch
    # on would change rather than leaving it to be discovered afterwards.
    #
    # Counted the way access is actually decided — a tab is reachable when any
    # action is ticked — rather than by counting rows. Rows outnumber granted
    # tabs several times over, and quoting that number would overstate what the
    # user is about to lose.
    from .access import _any_action_q, allowed_view_tabs

    # Counted the way access is decided — a tab is reachable when any action is
    # ticked — using that rule rather than a second copy of it. While the switch
    # is on, allowed_view_tabs answers for the individual matrix, so the group's
    # own count has to be asked for directly.
    group_tabs = (
        allowed_view_tabs(subject) if not profile.individual_permissions
        else set(GroupTabPermission.objects
                 .filter(group__in=subject.groups.all())
                 .filter(_any_action_q())
                 .values_list("tab_code", flat=True)))

    return render(request, "user_permissions.html", {
        "subject": subject,
        "individual": profile.individual_permissions,
        "matrix": _permission_matrix(saved),
        "actions": ACTIONS,
        "unenforced_actions": UNENFORCED_ACTIONS,
        "group_names": list(subject.groups.values_list("name", flat=True)),
        "group_tab_count": len(group_tabs),
        "own_tab_count": len(saved),
    })


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


# ---------------------------------------------------------------------------
# Employee Organization Access Master
# ---------------------------------------------------------------------------

#: The dimensions this page edits, as (all-flag, m2m field, posted field name).
#: One list so the view, the summary and the row loader cannot disagree about
#: what the page holds.
_ORG_SCOPES = [
    ("all_companies", "companies", "companies"),
    ("all_branches", "branches", "branches"),
    ("all_warehouses", "warehouses", "warehouses"),
    ("all_farms", "farms", "farms"),
    ("all_sheds", "sheds", "sheds"),
    ("all_cost_centres", "cost_centres", "cost_centres"),
]


def warehouse_branch_map():
    """Warehouse id -> branch id, from the Office Mapping master.

    Warehouse carries no branch column — that was replaced by
    ``inventory.Mapping`` (TYPE_SECTOR_BRANCH) — so every branch-derived answer
    about warehouses reads through here. A warehouse nobody has mapped is
    absent, which is what puts it outside any branch's scope.
    """
    from inventory.models import Mapping

    return dict(Mapping.objects
                .filter(type=Mapping.TYPE_SECTOR_BRANCH, to_id__isnull=False)
                .values_list("from_id", "to_id"))


def _org_access_options():
    """Everything the pickers offer, in the order the page lays them out.

    Each row of a cascading dimension carries its parent, so the picker can
    narrow to it: choose two branches and the warehouse and farm lists show
    only what belongs to those two. Offering the rest and quietly dropping them
    on save would be worse than not offering them at all.
    """
    from account.models import CompanyProfile, OrganizationCentre
    from broiler.models import Branch, BroilerBatch, BroilerFarm, BroilerFarmShed

    branch_of = warehouse_branch_map()
    warehouses = list(Warehouse.objects.order_by("name"))
    for w in warehouses:
        # 0 rather than None: an unmapped warehouse belongs to no branch, and a
        # parent id no branch can ever have is what keeps it out of every
        # branch-narrowed list without a special case in the template.
        w.branch_id = branch_of.get(w.id, 0)

    return {
        "companies": CompanyProfile.objects.order_by("id"),
        "branches": Branch.objects.order_by("branch_name"),
        "warehouses": warehouses,
        "farms": BroilerFarm.objects.select_related("branch").order_by("farm_name"),
        "sheds": BroilerFarmShed.objects.select_related("farm").order_by(
            "farm__farm_name", "unit_no"),
        "cost_centres": OrganizationCentre.objects.order_by("name"),
        "batches": BroilerBatch.objects.select_related("broiler_farm")
                   .order_by("-id"),
    }


def _drop_out_of_scope(profile):
    """Remove selections that fall outside the dimension above them.

    A warehouse belongs to a branch (through Office Mapping) and a shed to a
    farm. Naming one whose parent is not in scope would grant a place the
    branch selection says the employee has nothing to do with — so it is not
    stored. The picker already hides these; this is the rule the picker is only
    the front of, for anything that posts without it.

    Only *named* selections are pruned. Under "All" there is nothing to prune,
    because the answer is derived from the parent to begin with.
    """
    from broiler.models import BroilerFarm

    if not profile.all_branches:
        branch_ids = set(profile.branches.values_list("id", flat=True))

        if not profile.all_warehouses:
            branch_of = warehouse_branch_map()
            profile.warehouses.set([
                w for w in profile.warehouses.values_list("id", flat=True)
                if branch_of.get(w) in branch_ids])

        if not profile.all_farms:
            profile.farms.set(profile.farms.filter(branch_id__in=branch_ids))

    if not profile.all_sheds:
        # The farms in scope: those named, or those of the branches when farms
        # are left on "All".
        if profile.all_farms:
            farms = (BroilerFarm.objects.all() if profile.all_branches
                     else BroilerFarm.objects.filter(
                         branch_id__in=profile.branches.values_list("id", flat=True)))
        else:
            farms = profile.farms.all()
        profile.sheds.set(profile.sheds.filter(farm__in=farms))


def _org_access_row(profile, totals):
    """One saved profile as the list renders it.

    Counts rather than names: a row that says "All (12)" and one that says "3"
    are the two things a reader is scanning for, and spelling out twelve
    warehouses in a table cell tells them less, not more.

    ``totals`` is passed in rather than counted here — it is the same for every
    row, and counting it per row is one query per dimension per employee.
    """
    def count(all_flag, field, total):
        return f"All ({total})" if getattr(profile, all_flag) \
            else str(getattr(profile, field).count())

    options = totals
    return {
        "profile": profile,
        "employee": profile.employee,
        "branches": count("all_branches", "branches", options["branches"]),
        "warehouses": count("all_warehouses", "warehouses", options["warehouses"]),
        "farms": count("all_farms", "farms", options["farms"]),
        "sheds": count("all_sheds", "sheds", options["sheds"]),
        "cost_centres": count("all_cost_centres", "cost_centres",
                              options["cost_centres"]),
        "batch_visibility": profile.get_batch_visibility_display(),
    }


@login_required
def employee_access(request):
    """User > Employee Organization Access — one employee's data scope.

    Permissions (which tabs, which actions) stay with the groups; this decides
    which *rows*. Where a profile exists it replaces the group's data scope
    entirely — see user.services.scoping — so an employee with no profile is
    scoped exactly as they were before this page existed.
    """
    from .models import EmployeeAccessProfile

    if request.method == "POST":
        return _save_employee_access(request)

    profiles = (EmployeeAccessProfile.objects
                .select_related("employee", "employee__designation")
                .prefetch_related("branches", "warehouses", "farms", "sheds",
                                  "cost_centres")
                .order_by("employee__full_name"))
    options = _org_access_options()
    totals = {k: len(v) if isinstance(v, list) else v.count()
              for k, v in options.items()}
    return render(request, "employee_access.html", {
        "employees": Employee.objects.select_related(
            "designation", "department", "user").order_by("full_name"),
        "options": options,
        "rows": [_org_access_row(p, totals) for p in profiles],
        "batch_choices": EmployeeAccessProfile.BATCH_VISIBILITY_CHOICES,
    })


def _save_employee_access(request):
    from .models import EmployeeAccessProfile

    employee_id = request.POST.get("employee")
    if not employee_id:
        messages.error(request, "Choose whose access this is.")
        return redirect("employee_access")

    employee = get_object_or_404(Employee, pk=employee_id)
    with transaction.atomic():
        # One profile per employee, so saving the same person again edits
        # theirs rather than stacking a second scope nobody would see.
        profile, _ = EmployeeAccessProfile.objects.get_or_create(
            employee=employee)
        for all_flag, field, posted in _ORG_SCOPES:
            setattr(profile, all_flag, request.POST.get(f"all_{posted}") == "on")
            getattr(profile, field).set(request.POST.getlist(posted))
        # The picker narrows warehouses to the chosen branches and sheds to the
        # farms in scope, but the picker is not the rule. A selection that
        # falls outside its parent is dropped here too, so what is stored can
        # never grant more than the page showed.
        _drop_out_of_scope(profile)
        profile.batch_visibility = (request.POST.get("batch_visibility")
                                    or EmployeeAccessProfile.ALL_BATCHES)
        profile.batches.set(
            request.POST.getlist("batches")
            if profile.batch_visibility == EmployeeAccessProfile.SELECTED_BATCHES
            else [])
        profile.notes = (request.POST.get("notes") or "")[:250]
        profile.is_active = request.POST.get("is_active") == "on"
        profile.updated_by = request.user
        profile.save()

    messages.success(request, f"Access saved for {employee.full_name}.")
    return redirect("employee_access")


@login_required
def employee_access_row(request, pk):
    """One saved profile as JSON, for loading it back into the form."""
    from .models import EmployeeAccessProfile

    profile = get_object_or_404(EmployeeAccessProfile, pk=pk)
    data = {
        "id": profile.id,
        "employee": profile.employee_id,
        "batch_visibility": profile.batch_visibility,
        "batches": list(profile.batches.values_list("id", flat=True)),
        "notes": profile.notes,
        "is_active": profile.is_active,
    }
    for all_flag, field, posted in _ORG_SCOPES:
        data[f"all_{posted}"] = getattr(profile, all_flag)
        data[posted] = list(getattr(profile, field).values_list("id", flat=True))
    return JsonResponse(data)


@login_required
def employee_access_delete(request, pk):
    """Remove a profile — the employee falls back to their group's scope."""
    from .models import EmployeeAccessProfile

    profile = get_object_or_404(EmployeeAccessProfile, pk=pk)
    name = profile.employee.full_name
    profile.delete()
    messages.success(
        request, f"Access for {name} removed. They now follow their role's scope.")
    return redirect("employee_access")


@login_required
def employee_access_info(request, pk):
    """The read-only Employee Information panel for one employee."""
    employee = get_object_or_404(
        Employee.objects.select_related("designation", "department", "user"),
        pk=pk)
    user = employee.user
    return JsonResponse({
        # Same shape the list and the picker use — a bare 2263 beside an
        # EMP02263 in the table below reads as two different people.
        "employee_id": f"EMP{employee.employee_id:05d}" if employee.employee_id else "",
        "designation": getattr(employee.designation, "title", "") or "",
        "department": getattr(employee.department, "name", "") or "",
        # The role is whatever User Access gives the login — this page does not
        # set it, and says so by showing it and not offering to change it.
        "role": ", ".join(user.groups.values_list("name", flat=True)) if user else "",
        "login_status": ("Active" if user and user.is_active
                         else "Inactive" if user else "No login"),
        "date_of_joining": (employee.date_of_joining.strftime("%d-%b-%Y")
                            if employee.date_of_joining else ""),
    })
