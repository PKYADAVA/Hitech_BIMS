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
        "created_at": template.created_at.strftime("%Y-%m-%d %H:%M"),
        "updated_at": template.updated_at.strftime("%Y-%m-%d %H:%M"),
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
class SmsTransactionPageView(View):
    def get(self, request):
        from sales.models import Customer
        from purchase.models import Supplier
        from account.models import CompanyProfile

        templates_qs = SmsTemplate.objects.filter(is_active=True).order_by("name")
        return render(request, "sms_transaction.html", {
            "doc_sources": [(k, v["label"], v["party_type"], v.get("transaction", ""),
                             v.get("module", ""))
                            for k, v in DOC_SOURCES.items()],
            "templates": templates_qs,
            "templates_json": json.dumps([
                {"id": t.id, "name": t.name, "body": t.body,
                 "transaction": t.transaction, "module": t.module,
                 "module_display": t.get_module_display()}
                for t in templates_qs
            ]),
            "customers": Customer.objects.order_by("name"),
            "suppliers": Supplier.objects.order_by("name"),
            "company_name": CompanyProfile.get_solo().name,
        })


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
    """Grid rows for the transaction screen, with per-row variable context."""
    module = (request.GET.get("module") or "").strip()
    source = DOC_SOURCES.get(module)
    if not source:
        return JsonResponse({"error": "Select a valid module."}, status=400)
    rows = source["rows"](
        (request.GET.get("from_date") or "").strip() or None,
        (request.GET.get("to_date") or "").strip() or None,
        (request.GET.get("party") or "").strip() or None,
    )
    # Stamp each row with its successful-send history (per template), so the
    # grid can tell the sender exactly what already went out — and for which
    # template — before they send again.
    doc_nos = [r["doc_no"] for r in rows]
    sent_map = {}
    successful = (SmsMessage.objects
                  .filter(module=module, document_no__in=doc_nos,
                          status__in=["sent", "delivered", "mocked"])
                  .order_by("-created_at")
                  .values("document_no", "template_id", "template_name",
                          "mobile", "created_at"))
    for m in successful:
        sent_map.setdefault(m["document_no"], []).append({
            "template_id": m["template_id"],
            "template_name": m["template_name"],
            "mobile": m["mobile"],
            "sent_at": timezone.localtime(m["created_at"]).strftime("%d-%m-%Y %H:%M"),
        })
    for r in rows:
        r["sent_history"] = sent_map.get(r["doc_no"], [])
        r["already_sent"] = bool(r["sent_history"])
    return JsonResponse({"rows": rows, "party_type": source["party_type"]})


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
        qs = qs.filter(created_at__date__gte=from_date)
    if to_date:
        qs = qs.filter(created_at__date__lte=to_date)
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
