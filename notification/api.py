"""Mobile API v1 write/action endpoints for the SMS module.

Template + settings CRUD are registered via the generic ``register_model`` in
``api/urls.py``; this module adds the two *actions* that aren't plain CRUD —
sending a template to a phone number and retrying a failed message — reusing the
web app's own service layer (:func:`get_sms_service`) and logging to
``SmsMessage`` so sends show up in History, exactly like the web transaction send.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.serializers import serializer_factory
from api.viewsets import V1ViewMixin
from user.access import user_can

from .comm_sources import DOC_SOURCES, PARTY_TYPES, common_context, party_choices, sms_metrics
from .models import DeviceToken, SmsMessage, SmsSettings, SmsTemplate
from .push import send_push
from .services import get_sms_service
from .services.template_service import extract_placeholders

# SmsResult.status -> SmsMessage.status (mirrors notification.views).
_RESULT_STATUS_MAP = {
    "sent": "sent", "failed": "failed", "invalid": "invalid",
    "disabled": "disabled", "mocked": "mocked",
}

# Mirrors notification.views._MOBILE_RE.
_MOBILE_RE = re.compile(r"^\+?\d{10,15}$")


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


# Extend the factory serializer so FK fields still get their `_label` companions
# (e.g. modified_by_label) — while keeping the gateway API key write-only.
_SmsSettingsBase = serializer_factory(SmsSettings)


class SmsSettingsSerializer(_SmsSettingsBase):
    """Settings serializer that never leaks the gateway API key on read."""

    class Meta(_SmsSettingsBase.Meta):
        extra_kwargs = {"api_key": {"write_only": True, "required": False}}


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


class SmsDocSourcesView(V1ViewMixin, APIView):
    """GET /sms/doc-sources — the document types the transaction screen can pull.

    Feeds the phone's document-type filter; mirrors the tuple SmsTransactionPageView
    builds for the web page's <select id="module">.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([
            {"key": key, "label": src["label"], "party_type": src["party_type"],
             "module": src.get("module", ""), "transaction": src.get("transaction", "")}
            for key, src in DOC_SOURCES.items()
        ])


class SmsPartiesView(V1ViewMixin, APIView):
    """GET /sms/parties — party pickers for the transaction screen's Party filter.

    Mirrors SmsTransactionPageView's party_lists: one (id, name) list per party
    type, scoped to what this user may see (party_choices already applies the
    same customers_for/suppliers_for scoping the web page gets).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        choices = party_choices(request.user)
        return Response({
            key: {
                "label": label,
                "options": [{"id": pid, "name": name} for pid, name in choices.get(key, [])],
            }
            for key, label in PARTY_TYPES.items()
        })


class SmsTransactionDocumentsView(V1ViewMixin, APIView):
    """GET /sms/transaction/documents — rows eligible for SMS, for the phone's list.

    Mirrors notification.views.sms_transaction_source, party filter included.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        module = str(request.query_params.get("module") or "").strip()
        from_date = str(request.query_params.get("from_date") or "").strip() or None
        to_date = str(request.query_params.get("to_date") or "").strip() or None
        party_id = str(request.query_params.get("party") or "").strip() or None

        if module:
            source = DOC_SOURCES.get(module)
            if not source:
                raise ValidationError("Select a valid document type.")
            modules = [module]
        else:
            modules = list(DOC_SOURCES)
            # Party ids aren't comparable across different party tables when
            # browsing every document type at once (mirrors the web view).
            party_id = None

        rows = []
        for key in modules:
            for r in DOC_SOURCES[key]["rows"](from_date, to_date, party_id):
                r["module"] = key
                rows.append(r)
        rows.sort(key=lambda r: (r["date"], r["doc_id"]), reverse=True)

        doc_nos = {r["doc_no"] for r in rows}
        sent_map: dict = {}
        successful = (
            SmsMessage.objects
            .filter(module__in=modules, document_no__in=doc_nos,
                    status__in=["sent", "delivered", "mocked"])
            .order_by("-created_at")
            .values("module", "document_no", "template_id", "template_name",
                     "mobile", "created_at")
        )
        for m in successful:
            sent_map.setdefault((m["module"], m["document_no"]), []).append({
                "template_id": m["template_id"],
                "template_name": m["template_name"],
                "mobile": m["mobile"],
                "sent_at": timezone.localtime(m["created_at"]).strftime("%d-%m-%Y %H:%M"),
            })
        for r in rows:
            r["sent_history"] = sent_map.get((r["module"], r["doc_no"]), [])
            r["already_sent"] = bool(r["sent_history"])
        return Response({"rows": rows})


def _resolve_send(request, data) -> tuple:
    """Look up the document + template and render the message once.

    Shared by Send and Preview so a preview can never drift from what an
    actual send would produce. Returns (row, template, mobile, message).
    """
    source = DOC_SOURCES.get(str(data.get("module") or ""))
    if not source:
        raise ValidationError("Select a valid document type.")
    template = SmsTemplate.objects.filter(id=data.get("template_id")).first()
    if not template:
        raise ValidationError("Template not found.")
    if not template.is_active:
        raise ValidationError(f"Template '{template.name}' is inactive.")

    doc_id = data.get("doc_id")
    row = next(
        (r for r in source["rows"](None, None, None) if str(r["doc_id"]) == str(doc_id)),
        None,
    )
    if row is None:
        raise NotFound("Document not found.")
    mobile = str(row["mobile"] or "").strip().replace(" ", "")

    context = {**common_context(request.user), **row["context"]}
    message, err = _render_body(template, context)
    if err:
        raise ValidationError(err)
    return row, template, mobile, message


class SmsTransactionPreviewView(V1ViewMixin, APIView):
    """POST /sms/transaction/preview — render (never send) one document's SMS.

    Body: {module, doc_id, template_id}. Lets the phone show the exact message
    text + length/parts/unicode before committing to a send.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        row, template, mobile, message = _resolve_send(request, request.data)
        char_count, parts, is_unicode = sms_metrics(message)
        return Response({
            "party_name": row["party_name"], "mobile": mobile, "doc_no": row["doc_no"],
            "message": message, "char_count": char_count, "sms_parts": parts,
            "is_unicode": is_unicode,
        })


class SmsTransactionSendView(V1ViewMixin, APIView):
    """POST /sms/transaction/send — render + send one document's SMS.

    Body: {module, doc_id, template_id, force}. Mirrors notification.views.sms_send.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not user_can(request.user, "sms_transaction", "add"):
            raise PermissionDenied("You do not have permission to send SMS.")

        row, template, mobile, message = _resolve_send(request, request.data)
        if not mobile:
            raise ValidationError(f"{row['party_name']} has no mobile number.")
        if not _MOBILE_RE.match(mobile):
            raise ValidationError(f"Invalid mobile number '{mobile}' for {row['party_name']}.")

        if not request.data.get("force"):
            recent = SmsMessage.objects.filter(
                mobile=mobile, template=template, document_no=row["doc_no"],
                created_at__gte=timezone.now() - timedelta(minutes=1),
            ).exclude(status__in=["failed", "invalid", "rejected"]).exists()
            if recent:
                # 200, not 409: this is a decision for the sender to make (send
                # again or not), not a failure — the envelope collapses every
                # >=400 body into the generic error shape, which would bury
                # `duplicate` where the client can't easily read it.
                return Response({
                    "sent": False, "duplicate": True,
                    "error": "This SMS was already sent recently. Send again?",
                })

        char_count, parts, is_unicode = sms_metrics(message)
        options: dict = {}
        if template.dlt_template_id:
            options["dlt_template_id"] = template.dlt_template_id
        if template.sender_id:
            options["sender_id"] = template.sender_id
        result = get_sms_service().send_sms(mobile, message, options=options or None)

        module_key = str(request.data["module"])
        log = SmsMessage.objects.create(
            party_type=row["party_type"], party_id=row["party_id"], party_name=row["party_name"],
            mobile=mobile, module=module_key, document_no=row["doc_no"],
            template=template, template_name=template.name,
            message=message, char_count=char_count, sms_parts=parts, is_unicode=is_unicode,
            status=_RESULT_STATUS_MAP.get(result.status, "unknown"),
            gateway_message_id=result.message_id or "",
            gateway_status=result.status or "",
            gateway_response=getattr(result, "provider_response", None),
            api_request={"module": module_key, "doc_id": row["doc_id"],
                         "template": template.key, "source": "mobile"},
            error_message=result.error or "",
            sent_by=request.user, ip_address=_client_ip(request),
        )
        return Response({
            "sent": result.success, "status": log.status, "log_id": log.id,
            "error": result.error, "message_id": result.message_id,
        }, status=200 if result.success else 502)


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
