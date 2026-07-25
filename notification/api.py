"""Mobile API v1 write/action endpoints for the SMS module.

Template + settings CRUD are registered via the generic ``register_model`` in
``api/urls.py``; this module adds the two *actions* that aren't plain CRUD —
sending a template to a phone number and retrying a failed message — reusing the
web app's own service layer (:func:`get_sms_service`) and logging to
``SmsMessage`` so sends show up in History, exactly like the web transaction send.
"""
from __future__ import annotations

from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.viewsets import V1ViewMixin

from .comm_sources import sms_metrics
from .models import DeviceToken, SmsMessage, SmsSettings, SmsTemplate
from .push import send_push
from .services import get_sms_service
from .services.template_service import extract_placeholders

# SmsResult.status -> SmsMessage.status (mirrors notification.views).
_RESULT_STATUS_MAP = {
    "sent": "sent", "failed": "failed", "invalid": "invalid",
    "disabled": "disabled", "mocked": "mocked",
}


def _render_body(template, context: dict):
    """Render a template body against context; returns (message, error)."""
    unknown = sorted(n for n in extract_placeholders(template.body) if n not in context)
    if unknown:
        return None, f"Missing values for: {', '.join(unknown)}."
    try:
        return template.body.format(**context), None
    except (KeyError, IndexError, ValueError) as exc:
        return None, f"Failed to render template: {exc}."


def _client_ip(request) -> str:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    return (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")) or ""


class SmsSettingsSerializer(serializers.ModelSerializer):
    """Settings serializer that never leaks the gateway API key on read."""

    class Meta:
        model = SmsSettings
        fields = "__all__"
        extra_kwargs = {"api_key": {"write_only": True, "required": False}}
        read_only_fields = ["modified_by", "modified_at"]


class SmsTemplateSendView(V1ViewMixin, APIView):
    """POST /sms/templates/<id>/send — render + send a template to one number."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        template = SmsTemplate.objects.filter(pk=pk).first()
        if not template:
            raise NotFound("Template not found.")
        if not template.is_active:
            raise ValidationError("This template is inactive.")

        phone = str(request.data.get("phone") or "").strip().replace(" ", "")
        if not phone:
            raise ValidationError({"phone": ["Phone number is required."]})

        raw_ctx = request.data.get("context") or {}
        if not isinstance(raw_ctx, dict):
            raise ValidationError({"context": ["Must be an object of placeholder values."]})
        context = {str(k): str(v) for k, v in raw_ctx.items()}

        message, err = _render_body(template, context)
        if err:
            raise ValidationError(err)

        char_count, parts, is_unicode = sms_metrics(message)
        options: dict = {}
        if template.dlt_template_id:
            options["dlt_template_id"] = template.dlt_template_id
        if template.sender_id:
            options["sender_id"] = template.sender_id

        result = get_sms_service().send_sms(phone, message, options=options or None)

        log = SmsMessage.objects.create(
            party_type="manual", party_id=0,
            party_name=str(request.data.get("party_name") or phone),
            mobile=phone, module="manual", document_no="",
            template=template, template_name=template.name,
            message=message, char_count=char_count, sms_parts=parts, is_unicode=is_unicode,
            status=_RESULT_STATUS_MAP.get(result.status, "unknown"),
            gateway_message_id=result.message_id or "",
            gateway_status=result.status or "",
            gateway_response=getattr(result, "provider_response", None),
            api_request={"template": template.key, "context": context, "source": "mobile"},
            error_message=result.error or "",
            sent_by=request.user, ip_address=_client_ip(request),
        )
        return Response({
            "sent": result.success, "status": log.status, "log_id": log.id,
            "message_id": result.message_id, "error": result.error,
        })


class SmsMessageRetryView(V1ViewMixin, APIView):
    """POST /sms/messages/<id>/retry — re-send a failed message, keeping an audit trail."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        original = SmsMessage.objects.filter(pk=pk).first()
        if not original:
            raise NotFound("SMS record not found.")

        options: dict = {}
        if original.template and original.template.dlt_template_id:
            options["dlt_template_id"] = original.template.dlt_template_id
        result = get_sms_service().send_sms(original.mobile, original.message, options=options or None)

        log = SmsMessage.objects.create(
            party_type=original.party_type, party_id=original.party_id,
            party_name=original.party_name, mobile=original.mobile,
            module=original.module, document_no=original.document_no,
            template=original.template, template_name=original.template_name,
            message=original.message, char_count=original.char_count,
            sms_parts=original.sms_parts, is_unicode=original.is_unicode,
            status=_RESULT_STATUS_MAP.get(result.status, "unknown"),
            gateway_message_id=result.message_id or "",
            gateway_status=result.status or "",
            gateway_response=getattr(result, "provider_response", None),
            api_request=original.api_request,
            error_message=result.error or "",
            retry_of=original, retry_count=original.retry_count + 1,
            sent_by=request.user, ip_address=_client_ip(request),
        )
        original.retry_count += 1
        original.save(update_fields=["retry_count"])
        return Response({
            "sent": result.success, "status": log.status, "log_id": log.id,
            "error": result.error,
        })


class DeviceRegisterView(V1ViewMixin, APIView):
    """POST /devices/register — upsert this device's Expo push token for the user."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = str(request.data.get("token") or "").strip()
        if not token:
            raise ValidationError({"token": ["Push token is required."]})
        platform = str(request.data.get("platform") or "")[:20]
        # Reassign the token to the current user (device may switch accounts).
        obj, _ = DeviceToken.objects.update_or_create(
            token=token, defaults={"user": request.user, "platform": platform}
        )
        return Response({"registered": True, "id": obj.id})


class DeviceTestView(V1ViewMixin, APIView):
    """POST /devices/test — send a test push to all of the user's devices."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        tokens = list(
            DeviceToken.objects.filter(user=request.user).values_list("token", flat=True)
        )
        result = send_push(
            tokens, "Hitech BIMS", "Test notification ✓", data={"type": "test"}
        )
        return Response(result)
