# user/middleware.py
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

from .access import URLNAME_TO_TAB, resolve_action, user_can


class WebAccessMiddleware:
    """Enforces the Web-Access matrix per request:

    * list/detail pages (url-name is a tab code) require the tab's *view* right;
    * create/edit/delete pages (``customer_add``, ``branch_edit``, …) require the
      matching *add/edit/delete* right on the owning tab.

    Url-names that map to neither are left open, so core auth/user-management
    pages are never accidentally locked out. Superusers, ``admin`` access-
    profiles, and users whose groups have no matrix configuration all bypass
    (see ``user.access``).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Django admin is reserved for the super admin (full ERP rights). An
        # authenticated non-superuser is bounced even if they type /admin/ —
        # anonymous users still get the admin login page.
        if request.path.startswith("/admin"):
            user = getattr(request, "user", None)
            if user and user.is_authenticated and not user.is_superuser:
                messages.error(request, "The Django admin is restricted to the super admin.")
                return redirect("home")
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return None

        match = getattr(request, "resolver_match", None)
        if match is None:
            return None

        url_name = match.url_name
        tab = URLNAME_TO_TAB.get(url_name)
        if tab is not None:
            action = "view"
        else:
            resolved = resolve_action(url_name)
            if resolved is None:
                return None  # Not a matrix-controlled page.
            tab, action = resolved

        if user_can(user, tab, action):
            return None

        return self._deny(request, action)

    def _deny(self, request, action):
        # AJAX / non-GET (e.g. delete) gets a clean 403; page loads redirect home.
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        if is_ajax or request.method != "GET":
            return JsonResponse(
                {"error": f"You do not have permission to {action} this record."},
                status=403,
            )
        messages.error(
            request, "You do not have permission to access that page."
        )
        return redirect("home")
