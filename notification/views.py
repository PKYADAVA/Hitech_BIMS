"""In-app UI for managing editable SMS templates.

Mirrors the project's existing master-page pattern: a login-protected
``TemplateView`` renders the page and a class-based JSON API backs the
DataTable/modals via AJAX. Business logic stays in the service layer; these
views only perform CRUD on :class:`~notification.models.SmsTemplate`.
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .constants import SMS_MODULE_CHOICES, SMS_MODULE_TRANSACTIONS, transaction_label
from .models import SmsMessage, SmsTemplate, SmsTemplateCategory
from .services import get_sms_service
from .services.template_service import extract_placeholders
from Hitech_BIMS.entry_dates import date_from_query

logger = logging.getLogger("notification.sms")

_VALID_MODULES = {value for value, _ in SMS_MODULE_CHOICES}


def _template_to_dict(template: SmsTemplate) -> dict:
    return {
        "id": template.id,
        "key": template.key,
        "module": template.module,
        "module_display": template.get_module_display(),
        "transaction": template.transaction,
        "transaction_display": transaction_label(template.module, template.transaction),
        "name": template.name,
        "body": template.body,
        "description": template.description,
        "dlt_template_id": template.dlt_template_id,
        "category": template.category,
        "sms_type": template.sms_type,
        "sender_id": template.sender_id,
        "placeholders": sorted(extract_placeholders(template.body)),
        "is_active": template.is_active,
        "created_by": template.created_by.username if template.created_by else "",
        "modified_by": template.modified_by.username if template.modified_by else "",
        "created_at": timezone.localtime(template.created_at).strftime("%Y-%m-%d %H:%M"),
        "updated_at": timezone.localtime(template.updated_at).strftime("%Y-%m-%d %H:%M"),
    }


@method_decorator(login_required, name="dispatch")
class SmsTemplateManageView(View):
    """Render the SMS template management page."""

    def get(self, request):
        from .comm_sources import (SMS_VARIABLES, TRANSACTION_VARIABLES,
                                   GENERIC_VARIABLE_KEYS)
        context = {
            "modules": SMS_MODULE_CHOICES,
            "categories": SmsTemplateCategory.CHOICES,
            "sms_variables": SMS_VARIABLES,
            "module_transactions_json": json.dumps(SMS_MODULE_TRANSACTIONS),
            "transaction_variables_json": json.dumps(TRANSACTION_VARIABLES),
            "generic_variables_json": json.dumps(GENERIC_VARIABLE_KEYS),
        }
        return render(request, "sms_templates.html", context)


@method_decorator(login_required, name="dispatch")
class SmsTemplateAPI(View):
    """JSON CRUD endpoints for SMS templates."""

    def get(self, request, template_id=None) -> JsonResponse:
        if template_id:
            template = SmsTemplate.objects.filter(id=template_id).first()
            if not template:
                return JsonResponse({"error": "Template not found."}, status=404)
            return JsonResponse(_template_to_dict(template))

        templates = SmsTemplate.objects.all()
        return JsonResponse([_template_to_dict(t) for t in templates], safe=False)

    def post(self, request) -> JsonResponse:
        """Create a new template."""
        data = request.POST
        key = (data.get("key") or "").strip()
        module = (data.get("module") or "").strip()
        name = (data.get("name") or "").strip()
        body = (data.get("body") or "").strip()
        description = (data.get("description") or "").strip()
        dlt_template_id = (data.get("dlt_template_id") or "").strip()

        transaction = (data.get("transaction") or "").strip()
        error = self._validate(key, module, name, body, transaction)
        if error:
            return JsonResponse({"error": error}, status=400)
        if SmsTemplate.objects.filter(key=key).exists():
            return JsonResponse({"error": f"A template with key '{key}' already exists."},
                                status=400)

        SmsTemplate.objects.create(
            key=key, module=module, transaction=transaction, name=name, body=body,
            description=description, dlt_template_id=dlt_template_id,
            category=(data.get("category") or "general").strip(),
            sms_type=(data.get("sms_type") or "transactional").strip(),
            sender_id=(data.get("sender_id") or "").strip(),
            created_by=request.user, modified_by=request.user,
        )
        logger.info("SMS template created key=%s by user=%s", key, request.user)
        return JsonResponse({"message": "Template created."}, status=201)

    def put(self, request, template_id: int) -> JsonResponse:
        """Update an existing template. The key is immutable (code references it)."""
        template = SmsTemplate.objects.filter(id=template_id).first()
        if not template:
            return JsonResponse({"error": "Template not found."}, status=404)

        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid request payload."}, status=400)

        module = (data.get("module") or "").strip()
        name = (data.get("name") or "").strip()
        body = (data.get("body") or "").strip()
        description = (data.get("description") or "").strip()
        dlt_template_id = (data.get("dlt_template_id") or "").strip()

        transaction = (data.get("transaction") or "").strip()
        error = self._validate(template.key, module, name, body, transaction)
        if error:
            return JsonResponse({"error": error}, status=400)

        template.module = module
        template.transaction = transaction
        template.name = name
        template.body = body
        template.description = description
        template.dlt_template_id = dlt_template_id
        template.category = (data.get("category") or template.category).strip()
        template.sms_type = (data.get("sms_type") or template.sms_type).strip()
        template.sender_id = (data.get("sender_id") or "").strip()
        template.modified_by = request.user
        template.save(update_fields=[
            "module", "transaction", "name", "body", "description", "dlt_template_id",
            "category", "sms_type", "sender_id", "modified_by", "updated_at",
        ])
        logger.info("SMS template updated key=%s by user=%s", template.key, request.user)
        return JsonResponse({"message": "Template updated."})

    def delete(self, request, template_id: int) -> JsonResponse:
        """Delete a template row; sending falls back to the built-in default."""
        template = SmsTemplate.objects.filter(id=template_id).first()
        if not template:
            return JsonResponse({"error": "Template not found."}, status=404)
        key = template.key
        template.delete()
        logger.info("SMS template deleted key=%s by user=%s", key, request.user)
        return JsonResponse({"message": "Template deleted."})

    @staticmethod
    def _validate(key, module, name, body, transaction="") -> str:
        if not key:
            return "Key is required."
        if module not in _VALID_MODULES:
            return "Select a valid module."
        if transaction and not transaction_label(module, transaction):
            return "Select a valid transaction for the chosen module."
        if not name:
            return "Name is required."
        if not body:
            return "Message body is required."
        return ""


@login_required
def send_sms_template(request, template_id: int) -> JsonResponse:
    """Send this template to a phone number using values supplied in the form.

    Placeholder values arrive as ``var_<placeholder>`` fields to avoid clashing
    with the ``phone`` field. Sending honours SMS_ENABLED/SMS_MOCK, so on a
    disabled/mock setup nothing leaves the server.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    template = SmsTemplate.objects.filter(id=template_id).first()
    if not template:
        return JsonResponse({"error": "Template not found."}, status=404)

    phone = (request.POST.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"error": "Phone number is required."}, status=400)

    context = {
        name: request.POST.get(f"var_{name}", "")
        for name in extract_placeholders(template.body)
    }
    result = get_sms_service().send_template(template.key, phone, context)
    return JsonResponse(
        {
            "success": result.success,
            "status": result.status,
            "message_id": result.message_id,
            "error": result.error,
        },
        status=200 if result.success else 400,
    )


@login_required
def toggle_sms_template_active(request, template_id: int) -> JsonResponse:
    """Toggle a template's active flag."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    template = SmsTemplate.objects.filter(id=template_id).first()
    if not template:
        return JsonResponse({"error": "Template not found."}, status=404)
    template.is_active = not template.is_active
    template.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"message": "Template updated.", "is_active": template.is_active})


# ---------------------------------------------------------------------------
# SMS Transaction & History (enterprise SMS module)
# ---------------------------------------------------------------------------
import re as _re
from datetime import timedelta

from django.utils import timezone

from user.access import user_can
from .comm_sources import DOC_SOURCES, SMS_VARIABLES, common_context, sms_metrics

_MOBILE_RE = _re.compile(r"^\+?\d{10,15}$")

# SmsResult.status -> SmsMessage.status
_RESULT_STATUS_MAP = {
    "sent": "sent", "failed": "failed", "invalid": "invalid",
    "disabled": "disabled", "mocked": "mocked",
}


@method_decorator(login_required, name="dispatch")
class SmsHistoryPageView(View):
    def get(self, request):
        return render(request, "sms_history.html", {
            "doc_sources": [(k, v["label"]) for k, v in DOC_SOURCES.items()],
            "templates": SmsTemplate.objects.order_by("name"),
            "statuses": SmsMessage.STATUS_CHOICES,
        })


@login_required
def sms_transaction_source(request):
    """Grid rows for the transaction screen, with per-row variable context.

    An empty ``module`` means "All" — rows are pulled from every registered
    source and tagged with their real source key (``r["module"]``) so the
    sender/preview/history lookups below (and the frontend's send call) can
    always address the document's actual module, never the literal "All".
    """
    module = (request.GET.get("module") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip() or None
    to_date = (request.GET.get("to_date") or "").strip() or None
    party_id = (request.GET.get("party") or "").strip() or None

    if module:
        source = DOC_SOURCES.get(module)
        if not source:
            return JsonResponse({"error": "Select a valid module."}, status=400)
        modules = [module]
        party_type = source["party_type"]
    else:
        modules = list(DOC_SOURCES)
        party_type = None
        party_id = None  # party ids aren't comparable across different party tables

    rows = []
    for key in modules:
        for r in DOC_SOURCES[key]["rows"](from_date, to_date, party_id):
            r["module"] = key
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["doc_id"]), reverse=True)

    # Stamp each row with its successful-send history (per template), so the
    # grid can tell the sender exactly what already went out — and for which
    # template — before they send again.
    doc_nos = {r["doc_no"] for r in rows}
    sent_map = {}
    successful = (SmsMessage.objects
                  .filter(module__in=modules, document_no__in=doc_nos,
                          status__in=["sent", "delivered", "mocked"])
                  .order_by("-created_at")
                  .values("module", "document_no", "template_id", "template_name",
                          "mobile", "created_at"))
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
    return JsonResponse({"rows": rows, "party_type": party_type})


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    return (forwarded.split(",")[0].strip() if forwarded
            else request.META.get("REMOTE_ADDR"))


def _render_body(template, context):
    """Render a template body against context; returns (message, error)."""
    required = extract_placeholders(template.body)
    unknown = sorted(name for name in required if name not in context)
    if unknown:
        return None, f"Unknown placeholders in template: {', '.join(unknown)}."
    try:
        return template.body.format(**context), None
    except (KeyError, IndexError, ValueError) as exc:
        return None, f"Failed to render template: {exc}."


@login_required
def sms_send(request):
    """Render + send one document's SMS; called per selected row by the UI.

    Body: {module, doc_id, template_id, force}. ``force`` overrides the
    recent-duplicate guard after the user confirms.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "sms_transaction", "add"):
        return JsonResponse({"error": "You do not have permission to send SMS."}, status=403)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request payload."}, status=400)

    source = DOC_SOURCES.get(data.get("module") or "")
    if not source:
        return JsonResponse({"error": "Select a valid module."}, status=400)
    template = SmsTemplate.objects.filter(id=data.get("template_id")).first()
    if not template:
        return JsonResponse({"error": "Template not found."}, status=400)
    if not template.is_active:
        return JsonResponse({"error": f"Template '{template.name}' is inactive."}, status=400)

    row = next((r for r in source["rows"](None, None, None)
                if str(r["doc_id"]) == str(data.get("doc_id"))), None)
    if row is None:
        return JsonResponse({"error": "Document not found."}, status=404)
    mobile = (row["mobile"] or "").strip().replace(" ", "")
    if not mobile:
        return JsonResponse({"error": f"{row['party_name']} has no mobile number."}, status=400)
    if not _MOBILE_RE.match(mobile):
        return JsonResponse({"error": f"Invalid mobile number '{mobile}' for {row['party_name']}."}, status=400)

    context = {**common_context(request.user), **row["context"]}
    message, err = _render_body(template, context)
    if err:
        return JsonResponse({"error": err}, status=400)

    # Duplicate guard: same mobile + template + document within the last minute.
    if not data.get("force"):
        recent = SmsMessage.objects.filter(
            mobile=mobile, template=template, document_no=row["doc_no"],
            created_at__gte=timezone.now() - timedelta(minutes=1),
        ).exclude(status__in=["failed", "invalid", "rejected"]).exists()
        if recent:
            return JsonResponse({
                "duplicate": True,
                "error": "This SMS was already sent recently. Do you want to send again?",
            }, status=409)

    char_count, parts, is_unicode = sms_metrics(message)
    options = {}
    if template.dlt_template_id:
        options["dlt_template_id"] = template.dlt_template_id
    if template.sender_id:
        options["sender_id"] = template.sender_id
    result = get_sms_service().send_sms(mobile, message, options=options or None)

    log = SmsMessage.objects.create(
        party_type=row["party_type"], party_id=row["party_id"], party_name=row["party_name"],
        mobile=mobile, module=data["module"], document_no=row["doc_no"],
        template=template, template_name=template.name,
        message=message, char_count=char_count, sms_parts=parts, is_unicode=is_unicode,
        status=_RESULT_STATUS_MAP.get(result.status, "unknown"),
        gateway_message_id=result.message_id or "",
        gateway_status=result.status or "",
        gateway_response=result.provider_response,
        api_request={"module": data["module"], "doc_id": row["doc_id"],
                     "template": template.key, "context": context},
        error_message=result.error or "",
        sent_by=request.user, ip_address=_client_ip(request),
    )
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error, "message_id": result.message_id,
    }, status=200 if result.success else 502)


def _message_to_dict(m):
    return {
        "id": m.id, "created_at": timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M"),
        "party_type": m.party_type, "party_name": m.party_name, "mobile": m.mobile,
        "module": m.module, "module_label": DOC_SOURCES.get(m.module, {}).get("label", m.module),
        "document_no": m.document_no, "template_name": m.template_name,
        "message": m.message, "char_count": m.char_count, "sms_parts": m.sms_parts,
        "is_unicode": m.is_unicode, "status": m.status,
        "gateway_message_id": m.gateway_message_id, "gateway_status": m.gateway_status,
        "gateway_response": m.gateway_response, "error_message": m.error_message,
        "retry_count": m.retry_count, "retry_of": m.retry_of_id,
        "sent_by": m.sent_by.username if m.sent_by else "",
        "delivery_time": timezone.localtime(m.delivery_time).strftime("%Y-%m-%d %H:%M") if m.delivery_time else "",
        "can_retry": m.status in ("failed", "rejected", "expired", "invalid", "unknown"),
    }


@login_required
def sms_history(request):
    """Filterable history list plus today's dashboard stats."""
    qs = SmsMessage.objects.select_related("sent_by", "template")
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    if from_date:
        qs = qs.filter(created_at__date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(created_at__date__lte=date_from_query(to_date))
    for field, param in (("module", "module"), ("status", "status"),
                         ("template_id", "template"), ("mobile__icontains", "mobile")):
        value = (request.GET.get(param) or "").strip()
        if value:
            qs = qs.filter(**{field: value})
    q = (request.GET.get("q") or "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(party_name__icontains=q) | Q(document_no__icontains=q) |
                       Q(message__icontains=q) | Q(gateway_message_id__icontains=q))

    today = timezone.localdate()
    today_qs = SmsMessage.objects.filter(created_at__date=today)
    total_today = today_qs.count()
    ok_today = today_qs.filter(status__in=["sent", "delivered", "mocked"]).count()
    failed_today = today_qs.filter(status__in=["failed", "rejected", "expired", "invalid"]).count()
    pending_today = today_qs.filter(status__in=["queued", "accepted", "unknown"]).count()
    month_total = SmsMessage.objects.filter(
        created_at__year=today.year, created_at__month=today.month).count()

    return JsonResponse({
        "rows": [_message_to_dict(m) for m in qs[:500]],
        "stats": {
            "today": total_today, "delivered": ok_today, "failed": failed_today,
            "pending": pending_today,
            "success_rate": round(ok_today / total_today * 100, 1) if total_today else 0,
            "month": month_total,
        },
    })


@login_required
def sms_retry(request, message_id):
    """Re-send a failed SMS with the same message and mobile, keeping an audit trail."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "sms_history", "edit"):
        return JsonResponse({"error": "You do not have permission to retry SMS."}, status=403)
    original = SmsMessage.objects.filter(id=message_id).first()
    if not original:
        return JsonResponse({"error": "SMS record not found."}, status=404)

    options = {}
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
        gateway_response=result.provider_response,
        api_request=original.api_request,
        error_message=result.error or "",
        retry_of=original, retry_count=original.retry_count + 1,
        sent_by=request.user, ip_address=_client_ip(request),
    )
    original.retry_count += 1
    original.save(update_fields=["retry_count"])
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error,
    }, status=200 if result.success else 502)


# ---------------------------------------------------------------------------
# SMS Settings master (singleton configuration page)
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class SmsSettingsPageView(View):
    """View/edit the runtime SMS configuration (SmsSettings singleton)."""

    def get(self, request):
        from .conf import load_config
        from .models import SmsSettings

        row = SmsSettings.get_solo()
        cfg = load_config()
        return render(request, "sms_settings.html", {
            "row": row,
            "api_key_in_db": bool(row.api_key),
            "api_key_effective": bool(cfg.api_key),
            "effective": {
                "enabled": cfg.enabled, "mock": cfg.mock,
                "provider": cfg.provider,
                "sender_id": cfg.sender_id, "entity_id": cfg.entity_id,
                "country_code": cfg.default_country_code,
            },
            "can_edit": user_can(request.user, "sms_settings", "edit"),
        })

    def post(self, request):
        from .models import SmsSettings

        if not user_can(request.user, "sms_settings", "edit"):
            return JsonResponse({"error": "You do not have permission to change SMS settings."},
                                status=403)
        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)

        sender = str(data.get("sender_id", "")).strip().upper()
        if sender and not _re.fullmatch(r"[A-Z0-9]{3,10}", sender):
            return JsonResponse({"error": "Sender ID must be 3-10 letters/digits."}, status=400)
        country = str(data.get("default_country_code", "")).strip() or "91"
        if not _re.fullmatch(r"\d{1,4}", country):
            return JsonResponse({"error": "Country code must be 1-4 digits."}, status=400)

        row = SmsSettings.get_solo()
        row.enabled = bool(data.get("enabled"))
        row.mock = bool(data.get("mock"))
        row.sender_id = sender
        row.entity_id = str(data.get("entity_id", "")).strip()
        row.default_country_code = country
        if data.get("clear_api_key"):
            row.api_key = ""
        else:
            new_key = str(data.get("api_key", "")).strip()
            if new_key:
                row.api_key = new_key
        row.modified_by = request.user
        row.save()
        logger.info("SMS settings updated by user=%s enabled=%s mock=%s",
                    request.user.username, row.enabled, row.mock)
        return JsonResponse({"success": True})


@login_required
def sms_settings_test(request):
    """Send a test SMS with the currently saved configuration and log it."""

    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    if not user_can(request.user, "sms_settings", "edit"):
        return JsonResponse({"error": "You do not have permission to send test SMS."},
                            status=403)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    mobile = str(data.get("mobile", "")).strip()
    if not _re.fullmatch(r"\+?\d{10,15}", mobile):
        return JsonResponse({"error": "Enter a valid mobile number (10-15 digits)."}, status=400)

    from account.models import CompanyProfile
    message = (str(data.get("message", "")).strip()
               or f"Test SMS from {CompanyProfile.get_solo().name} (BIMS). Please ignore.")

    result = get_sms_service().send_sms(mobile, message)
    char_count, parts, is_unicode = sms_metrics(message)
    log = SmsMessage.objects.create(
        mobile=mobile, module="test", document_no="",
        template=None, template_name="(settings test)",
        message=message, char_count=char_count, sms_parts=parts, is_unicode=is_unicode,
        status=_RESULT_STATUS_MAP.get(result.status, "unknown"),
        gateway_message_id=result.message_id or "",
        gateway_status=result.status or "",
        gateway_response=result.provider_response,
        api_request={"module": "test"},
        error_message=result.error or "",
        sent_by=request.user, ip_address=_client_ip(request),
    )
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error, "message_id": result.message_id,
    }, status=200 if result.success else 502)


# ---------------------------------------------------------------------------
# WhatsApp templates (standalone manual-send module, mirrors SMS Templates)
# ---------------------------------------------------------------------------

from .constants import WHATSAPP_HEADER_TYPE_CHOICES
from .models import WhatsappMessage, WhatsappTemplate

# WhatsappResult.status -> WhatsappMessage.status
_WHATSAPP_RESULT_STATUS_MAP = {
    "sent": "sent", "failed": "failed", "invalid": "invalid",
    "disabled": "disabled", "mocked": "mocked",
}

# GET /api/v1/messages/{id} status string -> WhatsappMessage.STATUS_CHOICES.
# Per the docs: "Possible statuses: sent, delivered, read, failed." Maps
# 1:1 since those four already match our own choices; an unrecognized
# string (provider adds a new state) falls back to "unknown" rather than
# raising, so a status-poll refresh is never the thing that breaks the page.
_WHATSAPP_POLL_STATUS_MAP = {
    "sent": "sent", "delivered": "delivered", "read": "read", "failed": "failed",
}


def _whatsapp_template_to_dict(template: WhatsappTemplate) -> dict:
    return {
        "id": template.id,
        "key": template.key,
        "module": template.module,
        "module_display": template.get_module_display(),
        "transaction": template.transaction,
        "transaction_display": transaction_label(template.module, template.transaction),
        "name": template.name,
        "template_name": template.template_name,
        "language": template.language,
        "parameter_map": template.parameter_map or [],
        "header_type": template.header_type,
        "header_media_url": template.header_media_url,
        "description": template.description,
        "category": template.category,
        "is_active": template.is_active,
        "created_by": template.created_by.username if template.created_by else "",
        "modified_by": template.modified_by.username if template.modified_by else "",
        "created_at": timezone.localtime(template.created_at).strftime("%Y-%m-%d %H:%M"),
        "updated_at": timezone.localtime(template.updated_at).strftime("%Y-%m-%d %H:%M"),
    }


@method_decorator(login_required, name="dispatch")
class WhatsappTemplateManageView(View):
    """Render the WhatsApp template management page."""

    def get(self, request):
        from .comm_sources import (SMS_VARIABLES, TRANSACTION_VARIABLES,
                                   GENERIC_VARIABLE_KEYS)

        context = {
            "modules": SMS_MODULE_CHOICES,
            "categories": SmsTemplateCategory.CHOICES,
            "header_types": WHATSAPP_HEADER_TYPE_CHOICES,
            "sms_variables": SMS_VARIABLES,
            "module_transactions_json": json.dumps(SMS_MODULE_TRANSACTIONS),
            "transaction_variables_json": json.dumps(TRANSACTION_VARIABLES),
            "generic_variables_json": json.dumps(GENERIC_VARIABLE_KEYS),
        }
        return render(request, "whatsapp_templates.html", context)


@method_decorator(login_required, name="dispatch")
class WhatsappTemplateAPI(View):
    """JSON CRUD endpoints for WhatsApp templates."""

    def get(self, request, template_id=None) -> JsonResponse:
        if template_id:
            template = WhatsappTemplate.objects.filter(id=template_id).first()
            if not template:
                return JsonResponse({"error": "Template not found."}, status=404)
            return JsonResponse(_whatsapp_template_to_dict(template))

        templates = WhatsappTemplate.objects.all()
        return JsonResponse([_whatsapp_template_to_dict(t) for t in templates], safe=False)

    def post(self, request) -> JsonResponse:
        """Create a new template."""
        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid request payload."}, status=400)

        key = (data.get("key") or "").strip()
        module = (data.get("module") or "").strip()
        name = (data.get("name") or "").strip()
        template_name = (data.get("template_name") or "").strip()
        transaction = (data.get("transaction") or "").strip()
        error = self._validate(key, module, name, template_name, transaction)
        if error:
            return JsonResponse({"error": error}, status=400)
        if WhatsappTemplate.objects.filter(key=key).exists():
            return JsonResponse({"error": f"A template with key '{key}' already exists."},
                                status=400)

        WhatsappTemplate.objects.create(
            key=key, module=module, transaction=transaction, name=name,
            template_name=template_name, language=(data.get("language") or "en_US").strip(),
            parameter_map=data.get("parameter_map") or [],
            header_type=(data.get("header_type") or "none").strip(),
            header_media_url=(data.get("header_media_url") or "").strip(),
            description=(data.get("description") or "").strip(),
            category=(data.get("category") or "general").strip(),
            created_by=request.user, modified_by=request.user,
        )
        logger.info("WhatsApp template created key=%s by user=%s", key, request.user)
        return JsonResponse({"message": "Template created."}, status=201)

    def put(self, request, template_id: int) -> JsonResponse:
        """Update an existing template. The key is immutable (code references it)."""
        template = WhatsappTemplate.objects.filter(id=template_id).first()
        if not template:
            return JsonResponse({"error": "Template not found."}, status=404)

        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid request payload."}, status=400)

        module = (data.get("module") or "").strip()
        name = (data.get("name") or "").strip()
        template_name = (data.get("template_name") or "").strip()
        transaction = (data.get("transaction") or "").strip()
        error = self._validate(template.key, module, name, template_name, transaction)
        if error:
            return JsonResponse({"error": error}, status=400)

        template.module = module
        template.transaction = transaction
        template.name = name
        template.template_name = template_name
        template.language = (data.get("language") or template.language).strip()
        template.parameter_map = data.get("parameter_map") or []
        template.header_type = (data.get("header_type") or "none").strip()
        template.header_media_url = (data.get("header_media_url") or "").strip()
        template.description = (data.get("description") or "").strip()
        template.category = (data.get("category") or template.category).strip()
        template.modified_by = request.user
        template.save(update_fields=[
            "module", "transaction", "name", "template_name", "language", "parameter_map",
            "header_type", "header_media_url", "description", "category",
            "modified_by", "updated_at",
        ])
        logger.info("WhatsApp template updated key=%s by user=%s", template.key, request.user)
        return JsonResponse({"message": "Template updated."})

    def delete(self, request, template_id: int) -> JsonResponse:
        template = WhatsappTemplate.objects.filter(id=template_id).first()
        if not template:
            return JsonResponse({"error": "Template not found."}, status=404)
        key = template.key
        template.delete()
        logger.info("WhatsApp template deleted key=%s by user=%s", key, request.user)
        return JsonResponse({"message": "Template deleted."})

    @staticmethod
    def _validate(key, module, name, template_name, transaction="") -> str:
        if not key:
            return "Key is required."
        if module not in _VALID_MODULES:
            return "Select a valid module."
        if transaction and not transaction_label(module, transaction):
            return "Select a valid transaction for the chosen module."
        if not name:
            return "Name is required."
        if not template_name:
            return "Meta template name is required."
        if not _re.fullmatch(r"[a-z0-9_]+", template_name):
            return "Template name must be lowercase letters, numbers and underscores only."
        return ""


@login_required
def toggle_whatsapp_template_active(request, template_id: int) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    template = WhatsappTemplate.objects.filter(id=template_id).first()
    if not template:
        return JsonResponse({"error": "Template not found."}, status=404)
    template.is_active = not template.is_active
    template.save(update_fields=["is_active", "updated_at"])
    return JsonResponse({"message": "Template updated.", "is_active": template.is_active})


@login_required
def check_whatsapp_contact(request) -> JsonResponse:
    """Advisory-only: is this phone number a contact LemIn AI already knows
    about? NOT a real "has WhatsApp" check — see
    ``WhatsappService.check_contact`` for why. Never blocks a send; the
    frontend uses this to show a soft warning before the user confirms.
    """
    phone = (request.GET.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"error": "Phone number is required."}, status=400)

    from .services.whatsapp_service import get_whatsapp_service

    known = get_whatsapp_service().check_contact(phone)
    return JsonResponse({"known": known})


@login_required
def send_whatsapp_template(request, template_id: int) -> JsonResponse:
    """Send this template to a phone number using values supplied in the form.

    Parameter values arrive as ``var_<name>`` fields, one per entry in the
    template's ``parameter_map``, mirroring ``send_sms_template``.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    template = WhatsappTemplate.objects.filter(id=template_id).first()
    if not template:
        return JsonResponse({"error": "Template not found."}, status=404)

    phone = (request.POST.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"error": "Phone number is required."}, status=400)

    context = {
        name: request.POST.get(f"var_{name}", "")
        for name in (template.parameter_map or [])
    }
    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().send_template(template.key, phone, context)
    WhatsappMessage.objects.create(
        mobile=phone, module=template.module, document_no="",
        template=template, template_name=template.template_name,
        status=_WHATSAPP_RESULT_STATUS_MAP.get(result.status, "unknown"),
        wamid=result.message_id or "",
        provider_message_id=result.provider_message_id or "",
        gateway_response=result.provider_response,
        api_request={"template_key": template.key},
        error_message=result.error or "",
        sent_by=request.user, ip_address=_client_ip(request),
    )
    return JsonResponse(
        {
            "success": result.success,
            "status": result.status,
            "message_id": result.message_id,
            "error": result.error,
        },
        status=200 if result.success else 400,
    )


# ---------------------------------------------------------------------------
# WhatsApp Settings master (singleton configuration page)
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class WhatsappSettingsPageView(View):
    """View/edit the runtime WhatsApp configuration (WhatsappSettings singleton)."""

    def get(self, request):
        from .conf import load_whatsapp_config
        from .models import WhatsappSettings

        row = WhatsappSettings.get_solo()
        cfg = load_whatsapp_config()
        return render(request, "whatsapp_settings.html", {
            "row": row,
            "api_key_in_db": bool(row.api_key),
            "api_key_effective": bool(cfg.api_key),
            "effective": {
                "enabled": cfg.enabled, "mock": cfg.mock, "provider": cfg.provider,
                "base_url": cfg.base_url,
            },
            "templates": WhatsappTemplate.objects.filter(is_active=True),
            "can_edit": user_can(request.user, "whatsapp_settings", "edit"),
        })

    def post(self, request):
        from .models import WhatsappSettings

        if not user_can(request.user, "whatsapp_settings", "edit"):
            return JsonResponse({"error": "You do not have permission to change WhatsApp settings."},
                                status=403)
        try:
            data = json.loads(request.body or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)

        row = WhatsappSettings.get_solo()
        row.enabled = bool(data.get("enabled"))
        row.mock = bool(data.get("mock"))
        if data.get("clear_api_key"):
            row.api_key = ""
        else:
            new_key = str(data.get("api_key", "")).strip()
            if new_key:
                row.api_key = new_key
        row.modified_by = request.user
        row.save()
        logger.info("WhatsApp settings updated by user=%s enabled=%s mock=%s",
                    request.user.username, row.enabled, row.mock)
        return JsonResponse({"success": True})


@login_required
def whatsapp_settings_test(request):
    """Send a test template message with the currently saved configuration and log it."""

    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    if not user_can(request.user, "whatsapp_settings", "edit"):
        return JsonResponse({"error": "You do not have permission to send a test WhatsApp message."},
                            status=403)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    mobile = str(data.get("mobile", "")).strip()
    if not _re.fullmatch(r"\+?\d{10,15}", mobile):
        return JsonResponse({"error": "Enter a valid mobile number (10-15 digits)."}, status=400)

    template_id = data.get("template_id")
    template = WhatsappTemplate.objects.filter(id=template_id, is_active=True).first()
    if not template:
        return JsonResponse({"error": "Select a valid template to test with."}, status=400)

    context = {
        name: str((data.get("parameters") or {}).get(name, ""))
        for name in (template.parameter_map or [])
    }
    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().send_template(template.key, mobile, context)
    log = WhatsappMessage.objects.create(
        mobile=mobile, module="test", document_no="",
        template=template, template_name=template.template_name,
        status=_WHATSAPP_RESULT_STATUS_MAP.get(result.status, "unknown"),
        wamid=result.message_id or "",
        provider_message_id=result.provider_message_id or "",
        gateway_response=result.provider_response,
        api_request={"module": "test"},
        error_message=result.error or "",
        sent_by=request.user, ip_address=_client_ip(request),
    )
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error, "message_id": result.message_id,
    }, status=200 if result.success else 502)


# ---------------------------------------------------------------------------
# WhatsApp Transaction (bulk-send from ERP documents, mirrors SMS Transaction)
# ---------------------------------------------------------------------------

@login_required
def whatsapp_transaction_source(request):
    """Grid rows for the WhatsApp transaction screen, with per-row variable
    context. Identical shape to ``sms_transaction_source`` — same DOC_SOURCES
    rows, just stamped with WhatsApp send history instead of SMS."""
    module = (request.GET.get("module") or "").strip()
    from_date = (request.GET.get("from_date") or "").strip() or None
    to_date = (request.GET.get("to_date") or "").strip() or None
    party_id = (request.GET.get("party") or "").strip() or None

    if module:
        source = DOC_SOURCES.get(module)
        if not source:
            return JsonResponse({"error": "Select a valid module."}, status=400)
        modules = [module]
        party_type = source["party_type"]
    else:
        modules = list(DOC_SOURCES)
        party_type = None
        party_id = None

    rows = []
    for key in modules:
        for r in DOC_SOURCES[key]["rows"](from_date, to_date, party_id):
            r["module"] = key
            rows.append(r)
    rows.sort(key=lambda r: (r["date"], r["doc_id"]), reverse=True)

    doc_nos = {r["doc_no"] for r in rows}
    sent_map = {}
    successful = (WhatsappMessage.objects
                  .filter(module__in=modules, document_no__in=doc_nos,
                          status__in=["sent", "delivered", "read", "mocked"])
                  .order_by("-created_at")
                  .values("module", "document_no", "template_id", "template_name",
                          "mobile", "created_at"))
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
    return JsonResponse({"rows": rows, "party_type": party_type})


@login_required
def whatsapp_transaction_send(request):
    """Send one document's WhatsApp template; called per selected row by the UI.

    Body: {module, doc_id, template_id, force}. ``force`` overrides the
    recent-duplicate guard after the user confirms. Mirrors ``sms_send``.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "whatsapp_transaction", "add"):
        return JsonResponse({"error": "You do not have permission to send WhatsApp messages."},
                            status=403)
    try:
        data = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request payload."}, status=400)

    source = DOC_SOURCES.get(data.get("module") or "")
    if not source:
        return JsonResponse({"error": "Select a valid module."}, status=400)
    template = WhatsappTemplate.objects.filter(id=data.get("template_id")).first()
    if not template:
        return JsonResponse({"error": "Template not found."}, status=400)
    if not template.is_active:
        return JsonResponse({"error": f"Template '{template.name}' is inactive."}, status=400)

    row = next((r for r in source["rows"](None, None, None)
                if str(r["doc_id"]) == str(data.get("doc_id"))), None)
    if row is None:
        return JsonResponse({"error": "Document not found."}, status=404)
    mobile = (row["mobile"] or "").strip().replace(" ", "")
    if not mobile:
        return JsonResponse({"error": f"{row['party_name']} has no mobile number."}, status=400)
    if not _MOBILE_RE.match(mobile):
        return JsonResponse({"error": f"Invalid mobile number '{mobile}' for {row['party_name']}."}, status=400)

    context = {**common_context(request.user), **row["context"]}

    # Duplicate guard: same mobile + template + document within the last minute.
    if not data.get("force"):
        recent = WhatsappMessage.objects.filter(
            mobile=mobile, template=template, document_no=row["doc_no"],
            created_at__gte=timezone.now() - timedelta(minutes=1),
        ).exclude(status__in=["failed", "invalid"]).exists()
        if recent:
            return JsonResponse({
                "duplicate": True,
                "error": "This WhatsApp message was already sent recently. Do you want to send again?",
            }, status=409)

    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().send_template(template.key, mobile, context)
    log = WhatsappMessage.objects.create(
        party_type=row["party_type"], party_id=row["party_id"], party_name=row["party_name"],
        mobile=mobile, module=data["module"], document_no=row["doc_no"],
        template=template, template_name=template.template_name,
        status=_WHATSAPP_RESULT_STATUS_MAP.get(result.status, "unknown"),
        wamid=result.message_id or "",
        provider_message_id=result.provider_message_id or "",
        gateway_response=result.provider_response,
        api_request={"module": data["module"], "doc_id": row["doc_id"],
                     "template": template.key, "context": context},
        error_message=result.error or "",
        sent_by=request.user, ip_address=_client_ip(request),
    )
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error, "message_id": result.message_id,
    }, status=200 if result.success else 502)


# ---------------------------------------------------------------------------
# WhatsApp History (mirrors SMS History — see sms_history/_message_to_dict)
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class WhatsappHistoryPageView(View):
    def get(self, request):
        return render(request, "whatsapp_history.html", {
            "doc_sources": [(k, v["label"]) for k, v in DOC_SOURCES.items()],
            "templates": WhatsappTemplate.objects.order_by("name"),
            "statuses": WhatsappMessage.STATUS_CHOICES,
        })


#: Statuses that can still change — worth offering a Refresh for. A message
#: already "read" or "failed" has nowhere further to go.
_WHATSAPP_REFRESHABLE_STATUSES = frozenset({"queued", "sent", "delivered", "unknown"})


def _whatsapp_message_to_dict(m):
    return {
        "id": m.id, "created_at": timezone.localtime(m.created_at).strftime("%Y-%m-%d %H:%M"),
        "party_type": m.party_type, "party_name": m.party_name, "mobile": m.mobile,
        "module": m.module, "module_label": DOC_SOURCES.get(m.module, {}).get("label", m.module),
        "document_no": m.document_no, "template_name": m.template_name,
        "status": m.status, "wamid": m.wamid,
        "has_provider_id": bool(m.provider_message_id),
        "gateway_response": m.gateway_response, "error_message": m.error_message,
        "retry_count": m.retry_count, "retry_of": m.retry_of_id,
        "sent_by": m.sent_by.username if m.sent_by else "",
        "can_retry": m.status in ("failed", "invalid", "unknown"),
        "can_refresh": bool(m.provider_message_id) and m.status in _WHATSAPP_REFRESHABLE_STATUSES,
    }


@login_required
def whatsapp_history(request):
    """Filterable history list plus today's dashboard stats — mirrors sms_history."""
    qs = WhatsappMessage.objects.select_related("sent_by", "template")
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    if from_date:
        qs = qs.filter(created_at__date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(created_at__date__lte=date_from_query(to_date))
    for field, param in (("module", "module"), ("status", "status"),
                         ("template_id", "template"), ("mobile__icontains", "mobile")):
        value = (request.GET.get(param) or "").strip()
        if value:
            qs = qs.filter(**{field: value})
    q = (request.GET.get("q") or "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(party_name__icontains=q) | Q(document_no__icontains=q) |
                       Q(wamid__icontains=q))

    today = timezone.localdate()
    today_qs = WhatsappMessage.objects.filter(created_at__date=today)
    total_today = today_qs.count()
    ok_today = today_qs.filter(status__in=["sent", "delivered", "read", "mocked"]).count()
    failed_today = today_qs.filter(status__in=["failed", "invalid"]).count()
    pending_today = today_qs.filter(status__in=["queued", "unknown"]).count()
    month_total = WhatsappMessage.objects.filter(
        created_at__year=today.year, created_at__month=today.month).count()

    return JsonResponse({
        "rows": [_whatsapp_message_to_dict(m) for m in qs[:500]],
        "stats": {
            "today": total_today, "delivered": ok_today, "failed": failed_today,
            "pending": pending_today,
            "success_rate": round(ok_today / total_today * 100, 1) if total_today else 0,
            "month": month_total,
        },
    })


@login_required
def whatsapp_history_refresh_status(request, message_id):
    """Poll LemIn AI for a message's current delivery status and update the
    stored row in place — view-only, so it uses the same "view" permission
    as the history page itself rather than "edit" (nothing about the send
    is being changed, only how accurately its outcome is recorded)."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "whatsapp_history", "view"):
        return JsonResponse({"error": "You do not have permission to view WhatsApp history."}, status=403)
    message = WhatsappMessage.objects.filter(id=message_id).first()
    if not message:
        return JsonResponse({"error": "WhatsApp record not found."}, status=404)
    if not message.provider_message_id:
        return JsonResponse({"error": "This message has no stored provider id to check — "
                                       "only messages sent after status polling was added can be refreshed."},
                            status=400)

    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().check_status(message.provider_message_id)
    if result is None:
        return JsonResponse({"error": "Could not reach the WhatsApp provider to check status. Try again shortly."},
                            status=502)
    raw_status, raw_response = result
    mapped = _WHATSAPP_POLL_STATUS_MAP.get(raw_status, "unknown")
    message.status = mapped
    if raw_response is not None:
        message.gateway_response = raw_response
    message.save(update_fields=["status", "gateway_response"])
    return JsonResponse({"success": True, "status": mapped, "raw_status": raw_status})


#: One click shouldn't fire an unbounded burst of gateway calls — cap a
#: bulk refresh to the most recent N still-pending messages. A user with
#: more than this many pending can run it again for the next batch.
_WHATSAPP_BULK_REFRESH_LIMIT = 50


@login_required
def whatsapp_history_bulk_refresh_status(request):
    """Refresh every still-pending message (within the current filters) in
    one click, instead of one row at a time. Same "view" permission as the
    single-row refresh — this only re-checks outcomes, it sends nothing."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "whatsapp_history", "view"):
        return JsonResponse({"error": "You do not have permission to view WhatsApp history."}, status=403)

    qs = WhatsappMessage.objects.filter(
        status__in=_WHATSAPP_REFRESHABLE_STATUSES,
    ).exclude(provider_message_id="")
    from_date = (request.GET.get("from_date") or "").strip()
    to_date = (request.GET.get("to_date") or "").strip()
    if from_date:
        qs = qs.filter(created_at__date__gte=date_from_query(from_date))
    if to_date:
        qs = qs.filter(created_at__date__lte=date_from_query(to_date))
    for field, param in (("module", "module"), ("template_id", "template"),
                         ("mobile__icontains", "mobile")):
        value = (request.GET.get(param) or "").strip()
        if value:
            qs = qs.filter(**{field: value})

    messages = list(qs.order_by("-created_at")[:_WHATSAPP_BULK_REFRESH_LIMIT])
    from .services.whatsapp_service import get_whatsapp_service

    service = get_whatsapp_service()
    updated, unchanged, failed = 0, 0, 0
    for message in messages:
        result = service.check_status(message.provider_message_id)
        if result is None:
            failed += 1
            continue
        raw_status, raw_response = result
        mapped = _WHATSAPP_POLL_STATUS_MAP.get(raw_status, "unknown")
        if mapped == message.status:
            unchanged += 1
            continue
        message.status = mapped
        if raw_response is not None:
            message.gateway_response = raw_response
        message.save(update_fields=["status", "gateway_response"])
        updated += 1

    return JsonResponse({
        "success": True, "checked": len(messages), "updated": updated,
        "unchanged": unchanged, "failed": failed,
        "more_pending": qs.count() > len(messages),
    })


def _whatsapp_message_preview(raw):
    """Best-effort one-line summary of a GET /api/v1/messages entry's
    ``payload``, whose shape varies by ``type``. Falls back to the type
    name itself for a shape this hasn't seen, rather than erroring —
    LemIn AI can add message types without this list growing to match."""
    payload = raw.get("payload") or {}
    kind = payload.get("type") or raw.get("type") or "unknown"
    if kind == "text":
        return payload.get("text", {}).get("body", "")
    if kind == "template":
        # The docs' own request/response examples don't show it, but a real
        # conversation entry carries a server-rendered "_display.body" with
        # the actual message text (placeholders already filled with the
        # parameters that were sent) — show that instead of just the
        # template's name, which told the reader nothing about what the
        # customer actually received.
        tmpl = payload.get("template", {})
        display_body = (payload.get("_display") or {}).get("body")
        if display_body:
            return display_body
        return f"Template: {tmpl.get('name', '')}"
    if kind in ("image", "video", "audio", "document"):
        media = payload.get(kind, {})
        caption = media.get("caption")
        return f"[{kind}]" + (f" {caption}" if caption else "")
    if kind == "interactive":
        return payload.get("interactive", {}).get("body", {}).get("text", "") or "[interactive message]"
    return f"[{kind}]"


def _whatsapp_message_media_id(raw):
    """The WhatsApp media id on an image/video/audio/document entry, for
    the "Download" action — or ``None`` for a message that carries no
    media (text, template, interactive)."""
    payload = raw.get("payload") or {}
    kind = payload.get("type") or raw.get("type") or ""
    if kind not in ("image", "video", "audio", "document"):
        return None
    return (payload.get(kind) or {}).get("id")


@login_required
def whatsapp_conversation(request):
    """Fetch the message thread with one phone number, for the "View
    Conversation" action on WhatsApp History rows. Read-only, so it uses the
    same "view" permission as the history page itself."""
    if not user_can(request.user, "whatsapp_history", "view"):
        return JsonResponse({"error": "You do not have permission to view WhatsApp history."}, status=403)
    phone = (request.GET.get("phone") or "").strip()
    if not phone:
        return JsonResponse({"error": "A phone number is required."}, status=400)
    page = (request.GET.get("page") or "1").strip()
    try:
        page = max(1, int(page))
    except ValueError:
        page = 1

    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().get_conversation(phone, per_page=50, page=page, order="asc")
    if result is None:
        return JsonResponse({"error": "Could not reach the WhatsApp provider to load this conversation. "
                                       "Try again shortly."}, status=502)
    raw_messages, meta = result
    messages = [{
        "id": m.get("id"),
        "direction": m.get("direction"),
        "type": m.get("type"),
        "status": m.get("status"),
        "preview": _whatsapp_message_preview(m),
        "media_id": _whatsapp_message_media_id(m),
        "created_at": m.get("created_at"),
    } for m in raw_messages]
    return JsonResponse({"messages": messages, "meta": meta})


@login_required
def whatsapp_send_service_message(request):
    """Send a free-text reply from the Conversation modal — only valid
    within the contact's 24-hour service window (the provider itself
    enforces this; see WhatsappService.send_text). Gated on the same
    "add" permission as sending a template, since this is also a genuine
    outbound send, not a read."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "whatsapp_transaction", "add"):
        return JsonResponse({"error": "You do not have permission to send WhatsApp messages."}, status=403)
    phone = (request.POST.get("phone") or "").strip()
    body = (request.POST.get("body") or "").strip()
    if not phone:
        return JsonResponse({"error": "Phone number is required."}, status=400)
    if not body:
        return JsonResponse({"error": "Message text is required."}, status=400)

    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().send_text(phone, body)
    log = WhatsappMessage.objects.create(
        mobile=phone, message=body,
        status=_WHATSAPP_RESULT_STATUS_MAP.get(result.status, "unknown"),
        wamid=result.message_id or "",
        provider_message_id=result.provider_message_id or "",
        gateway_response=result.provider_response,
        api_request={"type": "service_message"},
        error_message=result.error or "",
        sent_by=request.user, ip_address=_client_ip(request),
    )
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error, "message_id": result.message_id,
    }, status=200 if result.success else 502)


#: party_type -> the LemIn AI group name a synced contact is filed under.
#: Plain names — LemIn AI creates any group it hasn't seen before, no IDs.
_WHATSAPP_SYNC_GROUP_BY_PARTY_TYPE = {
    "customer": "Customers", "supplier": "Suppliers",
    "farmer": "Farmers", "employee": "Employees",
}


@login_required
def whatsapp_sync_contact(request):
    """Create (or restore) a LemIn AI contact for one ERP party — manual,
    per-row action, not a bulk sync. Grouped by party_type and tagged with
    a party_type custom field so the LemIn AI dashboard's own contact list
    stays legible about where a contact came from. Gated on the same "add"
    permission as sending, since this writes a real contact into the
    connected LemIn AI account, not a local-only record."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "whatsapp_transaction", "add"):
        return JsonResponse({"error": "You do not have permission to sync WhatsApp contacts."}, status=403)
    name = (request.POST.get("name") or "").strip()
    phone = (request.POST.get("phone") or "").strip()
    party_type = (request.POST.get("party_type") or "").strip()
    if not name or not phone:
        return JsonResponse({"error": "Name and phone number are required."}, status=400)

    custom_fields = [{"key": "party_type", "value": party_type}] if party_type else []
    group = _WHATSAPP_SYNC_GROUP_BY_PARTY_TYPE.get(party_type)
    groups = [group] if group else []

    from .services.whatsapp_service import get_whatsapp_service

    success, data = get_whatsapp_service().create_contact(
        name, phone, custom_fields=custom_fields, groups=groups)
    if not success:
        return JsonResponse({"error": data}, status=502)
    return JsonResponse({"success": True, "contact": data})


@login_required
def whatsapp_media_link(request):
    """Fetch a temporary download URL for one inbound media message, for
    the Conversation modal's "Download" action. Read-only, so it uses the
    same "view" permission as the history page itself."""
    if not user_can(request.user, "whatsapp_history", "view"):
        return JsonResponse({"error": "You do not have permission to view WhatsApp history."}, status=403)
    media_id = (request.GET.get("media_id") or "").strip()
    if not media_id:
        return JsonResponse({"error": "A media id is required."}, status=400)

    from .services.whatsapp_service import get_whatsapp_service

    link = get_whatsapp_service().get_media_link(media_id)
    if link is None:
        return JsonResponse({"error": "Could not reach the WhatsApp provider to fetch this file. "
                                       "Try again shortly."}, status=502)
    return JsonResponse({"success": True, **link})


@login_required
def whatsapp_history_retry(request, message_id):
    """Re-send a failed WhatsApp message with the same template and context,
    keeping an audit trail. Mirrors sms_retry — context is replayed from the
    original send's own api_request, since (unlike SMS) there's no stored
    free-text message to resend verbatim."""
    if request.method != "POST":
        return JsonResponse({"error": "Invalid request method."}, status=400)
    if not user_can(request.user, "whatsapp_history", "edit"):
        return JsonResponse({"error": "You do not have permission to retry WhatsApp messages."}, status=403)
    original = WhatsappMessage.objects.filter(id=message_id).first()
    if not original:
        return JsonResponse({"error": "WhatsApp record not found."}, status=404)
    if not original.template:
        return JsonResponse({"error": "Original template no longer exists."}, status=400)

    context = (original.api_request or {}).get("context") or {}

    from .services.whatsapp_service import get_whatsapp_service

    result = get_whatsapp_service().send_template(original.template.key, original.mobile, context)
    log = WhatsappMessage.objects.create(
        party_type=original.party_type, party_id=original.party_id,
        party_name=original.party_name, mobile=original.mobile,
        module=original.module, document_no=original.document_no,
        template=original.template, template_name=original.template_name,
        status=_WHATSAPP_RESULT_STATUS_MAP.get(result.status, "unknown"),
        wamid=result.message_id or "",
        provider_message_id=result.provider_message_id or "",
        gateway_response=result.provider_response,
        api_request=original.api_request,
        error_message=result.error or "",
        retry_of=original, retry_count=original.retry_count + 1,
        sent_by=request.user, ip_address=_client_ip(request),
    )
    original.retry_count += 1
    original.save(update_fields=["retry_count"])
    return JsonResponse({
        "success": result.success, "status": log.status, "log_id": log.id,
        "error": result.error,
    }, status=200 if result.success else 502)


@method_decorator(login_required, name="dispatch")
class NotificationTransactionPageView(View):
    """Merged SMS + WhatsApp Transaction screen -- one filter bar and grid,
    a channel toggle swaps which templates/Send endpoint are in play.

    Gated by its own "notification_transaction" tab (view access to reach
    the page at all), but sending on each channel still goes through that
    channel's own ``sms_transaction``/``whatsapp_transaction`` "add"
    permission inside ``sms_send``/``whatsapp_transaction_send`` -- this
    view only decides which channel toggle(s) the page shows, via
    ``can_sms``/``can_whatsapp`` in the template context.
    """

    def get(self, request):
        from account.models import CompanyProfile

        from .comm_sources import PARTY_TYPES, party_choices

        can_sms = user_can(request.user, "sms_transaction", "view")
        can_whatsapp = user_can(request.user, "whatsapp_transaction", "view")

        sms_templates = (SmsTemplate.objects.filter(is_active=True).order_by("name")
                          if can_sms else SmsTemplate.objects.none())
        wa_templates = (WhatsappTemplate.objects.filter(is_active=True).order_by("name")
                         if can_whatsapp else WhatsappTemplate.objects.none())
        choices = party_choices(request.user)

        return render(request, "notification_transaction.html", {
            "can_sms": can_sms,
            "can_whatsapp": can_whatsapp,
            "doc_sources": [(k, v["label"], v["party_type"], v.get("transaction", ""),
                             v.get("module", ""))
                            for k, v in DOC_SOURCES.items()],
            "party_lists": [(key, label, choices.get(key, []))
                            for key, label in PARTY_TYPES.items()],
            "sms_templates_json": json.dumps([
                {"id": t.id, "name": t.name, "body": t.body,
                 "transaction": t.transaction, "module": t.module,
                 "module_display": t.get_module_display()}
                for t in sms_templates
            ]),
            "whatsapp_templates_json": json.dumps([
                {"id": t.id, "name": t.name, "template_name": t.template_name,
                 "parameter_map": t.parameter_map or [],
                 "transaction": t.transaction, "module": t.module,
                 "module_display": t.get_module_display()}
                for t in wa_templates
            ]),
            "company_name": CompanyProfile.get_solo().name,
        })
