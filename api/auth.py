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
