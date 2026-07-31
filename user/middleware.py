# user/middleware.py
import logging

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect

from .access import PUBLIC_URL_NAMES, URLNAME_TO_TAB, resolve_action, user_can

logger = logging.getLogger(__name__)

# Apps whose views are matrix-controlled. Anything outside these (Django admin,
# static, third-party) is not this middleware's business.
GUARDED_APPS = {
    "account", "alerts", "broiler", "environmental_monitoring", "hatchery",
    "hr", "inventory", "notification", "purchase", "sales", "tracking", "user",
    "api",
}

# One audit row per (url, method, user) per this many seconds. The point is to
# learn *which* endpoints are reached, not to count every hit, and a write on
# every request to a busy JSON list endpoint would not be free.
AUDIT_THROTTLE_SECONDS = 600


class WebAccessMiddleware:
    """Enforces the Web-Access matrix per request:

    * list/detail pages (url-name is a tab code) require the tab's *view* right;
    * create/edit/delete pages (``customer_add``, ``branch_edit``, …) require the
      matching *add/edit/delete* right on the owning tab.

    Url-names that map to neither are currently left open — most of the URL
    surface is in that state, including JSON list endpoints and some mutations.
    Closing it is the goal, but doing so blind would lock users out of endpoints
    nobody realised were in use, so those requests are *recorded* rather than
    refused (see :class:`user.models.WebAccessAudit`). Set
    ``WEB_ACCESS_ENFORCE=True`` once the audit table has been reviewed and the
    mapping filled in; until then this middleware behaves exactly as before.

    Superusers, ``admin`` access-profiles, and users whose groups have no matrix
    configuration all bypass (see ``user.access``).
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
                return self._unmapped(request, view_func, url_name, user)
            tab, action = resolved

        # Exporting is the "print" column, which nothing had ever checked.
        # Every report asks for it the same way (?export=excel|pdf|csv), so it
        # is enforced here rather than in each of the eighteen views.
        if action == "view" and self._is_export(request):
            action = "print"

        if user_can(user, tab, action):
            return None

        self._record(request, view_func, url_name, user, "denied", tab, action)
        return self._deny(request, action)

    @staticmethod
    def _is_export(request):
        value = (request.GET.get("export") or "").strip().lower()
        return bool(value) and value != "display"

    # ---- the unmapped surface --------------------------------------------

    def _unmapped(self, request, view_func, url_name, user):
        """A URL no tab claims. Recorded always; refused only once enforcing."""
        if not self._is_guarded(view_func) or url_name in PUBLIC_URL_NAMES:
            return None

        self._record(request, view_func, url_name, user, "unmapped", "", "")
        if not getattr(settings, "WEB_ACCESS_ENFORCE", False):
            return None            # audit only — behaviour unchanged
        logger.warning("web-access: refusing unmapped url %r for %s",
                       url_name, user.get_username())
        return self._deny(request, "open")

    @staticmethod
    def _is_guarded(view_func):
        module = getattr(view_func, "__module__", "") or ""
        cls = getattr(view_func, "cls", None) or getattr(view_func, "view_class", None)
        if cls is not None:
            module = getattr(cls, "__module__", module) or module
        return module.split(".")[0] in GUARDED_APPS

    def _record(self, request, view_func, url_name, user, verdict, tab, action):
        username = user.get_username()
        throttle = f"wa:audit:{verdict}:{url_name}:{request.method}:{username}"
        if cache.get(throttle):
            return
        cache.set(throttle, 1, AUDIT_THROTTLE_SECONDS)

        from django.db.models import F
        from .models import WebAccessAudit

        try:
            updated = WebAccessAudit.objects.filter(
                url_name=url_name, method=request.method, verdict=verdict,
                username=username).update(hits=F("hits") + 1)
            if not updated:
                WebAccessAudit.objects.create(
                    url_name=url_name, method=request.method, verdict=verdict,
                    username=username, path=request.path[:300],
                    view=self._view_path(view_func), tab_code=tab, action=action)
        except Exception:
            # Auditing must never be the reason a page fails to load.
            logger.exception("web-access: could not record %s for %r", verdict, url_name)

    @staticmethod
    def _view_path(view_func):
        cls = getattr(view_func, "cls", None) or getattr(view_func, "view_class", None)
        target = cls or view_func
        module = getattr(target, "__module__", "")
        name = getattr(target, "__qualname__", getattr(target, "__name__", ""))
        return f"{module}.{name}"[:200]

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
