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

from .constants import SMS_MODULE_CHOICES
from .models import SmsTemplate
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
        "name": template.name,
        "body": template.body,
        "description": template.description,
        "dlt_template_id": template.dlt_template_id,
        "placeholders": sorted(extract_placeholders(template.body)),
        "is_active": template.is_active,
        "updated_at": template.updated_at.strftime("%Y-%m-%d %H:%M"),
    }


@method_decorator(login_required, name="dispatch")
class SmsTemplateManageView(View):
    """Render the SMS template management page."""

    def get(self, request):
        context = {"modules": SMS_MODULE_CHOICES}
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

        error = self._validate(key, module, name, body)
        if error:
            return JsonResponse({"error": error}, status=400)
        if SmsTemplate.objects.filter(key=key).exists():
            return JsonResponse({"error": f"A template with key '{key}' already exists."},
                                status=400)

        SmsTemplate.objects.create(
            key=key, module=module, name=name, body=body,
            description=description, dlt_template_id=dlt_template_id,
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

        error = self._validate(template.key, module, name, body)
        if error:
            return JsonResponse({"error": error}, status=400)

        template.module = module
        template.name = name
        template.body = body
        template.description = description
        template.dlt_template_id = dlt_template_id
        template.save(update_fields=[
            "module", "name", "body", "description", "dlt_template_id", "updated_at",
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
    def _validate(key, module, name, body) -> str:
        if not key:
            return "Key is required."
        if module not in _VALID_MODULES:
            return "Select a valid module."
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
