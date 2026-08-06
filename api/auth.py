"""JWT authentication for mobile clients.

Runs *alongside* the web app's session auth — both authentication classes are
enabled globally (see settings ``REST_FRAMEWORK``), so the browser keeps using
the session cookie while mobile uses bearer tokens. Because JWT auth is not
``SessionAuthentication``, DRF does not enforce CSRF on these calls, so mobile
writes work without CSRF while the web app keeps its CSRF protection intact.

Endpoints (all under ``/api/v1/auth/``):
    POST login    -> {access, refresh, user}   (rate-limited)
    POST refresh  -> {access}                    (rotates + blacklists old)
    POST logout   -> blacklist the given refresh token (per-device logout)
    GET  me       -> current user's profile
"""
from __future__ import annotations

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .envelope import EnvelopeJSONRenderer
from .exceptions import api_exception_handler


# --- schema-only serializers (document the auth responses for the client) --- #
class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.CharField()
    full_name = serializers.CharField()
    is_staff = serializers.BooleanField()
    is_superuser = serializers.BooleanField()
    role = serializers.CharField()
    department = serializers.CharField()
    groups = serializers.ListField(child=serializers.CharField())


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class TokenPairSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UserSerializer()


class RefreshRequestSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class AccessSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField(required=False)


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ChangePasswordRequestSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField()


def _user_payload(user) -> dict:
    """Compact, mobile-friendly view of the authenticated user."""
    profile = getattr(user, "userprofile", None)
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": user.email,
        "full_name": user.get_full_name(),
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
        "role": getattr(profile, "role", "") or "",
        "department": getattr(profile, "department", "") or "",
        "groups": list(user.groups.values_list("name", flat=True)),
        # Which employee this login *is*, if any. Null for a login with no
        # employee record, which is the signal a form needs to decide between
        # "your name, fixed" and "choose whose".
        **_employee_identity(user),
    }


def _employee_identity(user) -> dict:
    from hr.models import Employee

    found = Employee.objects.filter(user=user).values("id", "full_name").first()
    return {
        "employee": found["id"] if found else None,
        "employee_name": found["full_name"] if found else "",
    }


class LoginSerializer(TokenObtainPairSerializer):
    """Adds the user block to the standard ``{access, refresh}`` response."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = _user_payload(self.user)
        return data


class _V1AuthView:
    """Shared v1 wiring for the SimpleJWT views (envelope + error shape)."""

    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def get_exception_handler(self):
        return api_exception_handler


class LoginView(_V1AuthView, TokenObtainPairView):
    serializer_class = LoginSerializer


class RefreshView(_V1AuthView, TokenRefreshView):
    pass


class LogoutView(APIView):
    """Blacklist a refresh token → logs out that one device/session."""

    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [IsAuthenticated]

    def get_exception_handler(self):
        return api_exception_handler

    def post(self, request):
        token = request.data.get("refresh")
        if not token:
            return Response(
                {"code": "validation_error", "message": "A 'refresh' token is required.", "fields": {}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            RefreshToken(token).blacklist()
        except Exception:
            # Already expired/blacklisted/invalid — logout is idempotent.
            pass
        return Response({"detail": "Logged out."}, status=status.HTTP_200_OK)


class MeView(APIView):
    """Return the authenticated user's profile."""

    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [IsAuthenticated]

    def get_exception_handler(self):
        return api_exception_handler

    def get(self, request):
        return Response(_user_payload(request.user))


class ChangePasswordView(APIView):
    """Change the authenticated user's password (checks the current one first).

    Existing JWTs stay valid (JWT is stateless) so the user isn't logged out of
    this or other devices — matching the web app's ``update_session_auth_hash``
    behaviour of keeping the current session alive after a password change.
    """

    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [IsAuthenticated]

    def get_exception_handler(self):
        return api_exception_handler

    @extend_schema(request=ChangePasswordRequestSerializer, responses=DetailSerializer)
    def post(self, request):
        current = request.data.get("current_password") or ""
        new = request.data.get("new_password") or ""
        user = request.user

        if not user.check_password(current):
            return Response(
                {"code": "validation_error", "message": "Your current password is incorrect.",
                 "fields": {"current_password": ["Incorrect password."]}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            validate_password(new, user)
        except DjangoValidationError as exc:
            return Response(
                {"code": "validation_error", "message": "Password does not meet the requirements.",
                 "fields": {"new_password": list(exc.messages)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new)
        user.save(update_fields=["password"])
        return Response({"detail": "Password changed."})


class PermissionsView(APIView):
    """Return the authenticated user's effective module (nav) + tab access.

    Drives per-user gating in the mobile app: `unrestricted` (superuser / no
    matrix configured → sees everything), `nav_groups` (top-level modules the
    user may open), and `tabs` (viewable tab codes for finer gating).
    """

    renderer_classes = [EnvelopeJSONRenderer]
    permission_classes = [IsAuthenticated]

    def get_exception_handler(self):
        return api_exception_handler

    def get(self, request):
        from user.access import (
            NAV_GROUPS,
            _user_is_unrestricted,
            allowed_nav_groups,
            allowed_view_tabs,
            user_can,
            user_has_any_matrix_config,
        )

        u = request.user
        unrestricted = bool(_user_is_unrestricted(u))
        # No matrix configured → treat as full access (matches allowed_view_tabs).
        open_access = unrestricted or (
            bool(getattr(u, "is_authenticated", False)) and not user_has_any_matrix_config(u)
        )

        if open_access:
            module_actions = {
                nav: {"add": True, "edit": True, "delete": True} for nav in NAV_GROUPS
            }
        else:
            from user.access import _tab_permission_qs

            # Whichever matrix answers for this user — their own when they have
            # been switched to individual permissions, their groups' otherwise.
            add_tabs, edit_tabs, del_tabs = set(), set(), set()
            for p in _tab_permission_qs(u).values(
                "tab_code", "can_add", "can_edit", "can_delete"
            ):
                if p["can_add"]:
                    add_tabs.add(p["tab_code"])
                if p["can_edit"]:
                    edit_tabs.add(p["tab_code"])
                if p["can_delete"]:
                    del_tabs.add(p["tab_code"])
            module_actions = {
                nav: {
                    "add": bool(codes & add_tabs),
                    "edit": bool(codes & edit_tabs),
                    "delete": bool(codes & del_tabs),
                }
                for nav, codes in NAV_GROUPS.items()
            }

        # Mobile Access is the second, phone-only gate. It can only narrow what
        # the matrix already allows, so it is applied last and never widens the
        # sets below. A user whose groups are unconfigured is unaffected.
        from user.services.mobile_access import (MOBILE_ACTIONS, NAV_MODULE,
                                                 REPORT_TAB_LIST, SCREEN_TABS,
                                                 allowed_mobile_navs,
                                                 module_order, screen_perms)

        navs = allowed_mobile_navs(u, allowed_nav_groups(u))
        tabs = allowed_view_tabs(u)
        # Drop the tabs of a module the phone is not showing, or a hub tile
        # gated by RESOURCE_TABS would survive its module being switched off.
        # Tabs owned by no gated nav pass through untouched.
        gated = {code for nav, codes in NAV_GROUPS.items()
                 if nav in NAV_MODULE and nav not in navs for code in codes}
        module_actions = {nav: acts for nav, acts in module_actions.items()
                          if nav in navs or nav not in NAV_MODULE}

        # Per-screen actions. The web matrix decides what is possible, Mobile
        # Access decides what of that reaches the phone; the client hides
        # buttons from this rather than from the module-wide flags, so an
        # "Edit off for Daily Entry" tick has something to act on.
        mobile = screen_perms(u)
        tab_actions = {}
        # Reports are view-only, so only that column is meaningful for them.
        for tab in list(SCREEN_TABS) + list(REPORT_TAB_LIST):
            if tab in gated or tab not in tabs:
                continue
            report = tab in REPORT_TAB_LIST
            allowed = mobile.get(tab) if mobile is not None else None
            tab_actions[tab] = {
                action: (
                    (True if open_access else user_can(u, tab, action))
                    and (allowed is None or bool(allowed.get(action)))
                ) if (action == "view" or not report) else False
                for action in MOBILE_ACTIONS
            }

        # A screen whose View is unticked must leave `tabs` too — the hub
        # filters its tiles on that set, so leaving it in would show a tile for
        # a screen the user may not open.
        hidden = {tab for tab, acts in tab_actions.items() if not acts["view"]}

        return Response({
            "unrestricted": unrestricted,
            "nav_groups": sorted(navs),
            # Registry/administrator order, not alphabetical — the phone lays
            # its home hub out in this order.
            "nav_order": module_order(u),
            "tabs": sorted(tabs - gated - hidden),
            "module_actions": module_actions,
            "tab_actions": tab_actions,
        })
