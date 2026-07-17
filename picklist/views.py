#pylint: disable=no-member

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

from .bindable_fields import BINDABLE_FIELDS
from .models import FieldPicklistBinding, Picklist, PicklistValue
from .sources import SOURCE_MODEL_CHOICES


@login_required
def picklists(request):
    return render(request, "picklist/picklists.html", {
        "source_model_choices": SOURCE_MODEL_CHOICES,
    })


@login_required
def field_bindings(request):
    return render(request, "picklist/field_bindings.html", {
        "bindable_fields": BINDABLE_FIELDS,
        "picklists": Picklist.objects.filter(is_active=True).order_by("name"),
    })


def _error(e):
    return JsonResponse({"error": " ".join(e.messages) if hasattr(e, "messages") else str(e)}, status=400)


@method_decorator(login_required, name="dispatch")
class PicklistAPI(View):

    @staticmethod
    def _serialize(pl):
        return {
            "id": pl.id,
            "key": pl.key,
            "name": pl.name,
            "source_type": pl.source_type,
            "source_model_key": pl.source_model_key,
            "source_label": pl.source_label,
            "is_active": pl.is_active,
            "value_count": pl.values.count() if pl.source_type == Picklist.SourceType.STATIC else None,
        }

    def get(self, request, id=None):
        if id:
            try:
                pl = Picklist.objects.get(id=id)
            except Picklist.DoesNotExist:
                raise Http404("Picklist not found")
            return JsonResponse(self._serialize(pl))
        return JsonResponse([self._serialize(pl) for pl in Picklist.objects.all()], safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        pl = Picklist(
            key=(data.get("key") or "").strip(),
            name=(data.get("name") or "").strip(),
            source_type=data.get("source_type") or Picklist.SourceType.STATIC,
            source_model_key=data.get("source_model_key") or "",
        )
        try:
            pl.full_clean()
            pl.save()
        except ValidationError as e:
            return _error(e)
        return JsonResponse({"id": pl.id, "message": "Picklist created"}, status=201)

    def put(self, request, id):
        try:
            pl = Picklist.objects.get(id=id)
        except Picklist.DoesNotExist:
            raise Http404("Picklist not found")
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        for field in ("key", "name", "source_type", "source_model_key"):
            if field in data:
                setattr(pl, field, data[field] or "")
        if "is_active" in data:
            pl.is_active = bool(data["is_active"])
        try:
            pl.full_clean()
            pl.save()
        except ValidationError as e:
            return _error(e)
        return JsonResponse({"message": "Picklist updated"})

    def delete(self, request, id):
        try:
            pl = Picklist.objects.get(id=id)
        except Picklist.DoesNotExist:
            raise Http404("Picklist not found")
        pl.delete()
        return JsonResponse({"message": "Picklist deleted"})


@method_decorator(login_required, name="dispatch")
class PicklistValueAPI(View):

    @staticmethod
    def _serialize(v):
        return {
            "id": v.id, "value": v.value, "label": v.label,
            "sort_order": v.sort_order, "is_active": v.is_active,
        }

    def get(self, request, picklist_id, id=None):
        qs = PicklistValue.objects.filter(picklist_id=picklist_id)
        if id:
            try:
                return JsonResponse(self._serialize(qs.get(id=id)))
            except PicklistValue.DoesNotExist:
                raise Http404("Value not found")
        return JsonResponse([self._serialize(v) for v in qs], safe=False)

    def post(self, request, picklist_id):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        try:
            picklist = Picklist.objects.get(id=picklist_id)
        except Picklist.DoesNotExist:
            raise Http404("Picklist not found")
        value = PicklistValue(
            picklist=picklist,
            value=(data.get("value") or "").strip(),
            label=(data.get("label") or "").strip(),
            sort_order=data.get("sort_order") or 0,
        )
        try:
            value.full_clean()
            value.save()
        except ValidationError as e:
            return _error(e)
        return JsonResponse({"id": value.id, "message": "Value added"}, status=201)

    def put(self, request, picklist_id, id):
        try:
            value = PicklistValue.objects.get(id=id, picklist_id=picklist_id)
        except PicklistValue.DoesNotExist:
            raise Http404("Value not found")
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        for field in ("value", "label"):
            if field in data:
                setattr(value, field, (data[field] or "").strip())
        if "sort_order" in data:
            value.sort_order = data["sort_order"] or 0
        if "is_active" in data:
            value.is_active = bool(data["is_active"])
        try:
            value.full_clean()
            value.save()
        except ValidationError as e:
            return _error(e)
        return JsonResponse({"message": "Value updated"})

    def delete(self, request, picklist_id, id):
        try:
            value = PicklistValue.objects.get(id=id, picklist_id=picklist_id)
        except PicklistValue.DoesNotExist:
            raise Http404("Value not found")
        value.delete()
        return JsonResponse({"message": "Value deleted"})


@method_decorator(login_required, name="dispatch")
class FieldPicklistBindingAPI(View):

    @staticmethod
    def _serialize(b):
        return {
            "id": b.id,
            "app_label": b.app_label,
            "model_name": b.model_name,
            "field_name": b.field_name,
            "field_path": f"{b.app_label}.{b.model_name}.{b.field_name}",
            "human_label": b.human_label,
            "mode": b.mode,
            "picklist": b.picklist_id,
            "picklist_name": str(b.picklist) if b.picklist_id else "",
            "is_required": b.is_required,
        }

    def get(self, request, id=None):
        qs = FieldPicklistBinding.objects.select_related("picklist")
        if id:
            try:
                return JsonResponse(self._serialize(qs.get(id=id)))
            except FieldPicklistBinding.DoesNotExist:
                raise Http404("Binding not found")
        return JsonResponse([self._serialize(b) for b in qs], safe=False)

    def post(self, request):
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        try:
            app_label, model_name, field_name = (data.get("field_path") or "").split(".")
        except ValueError:
            return JsonResponse({"error": "Select a field."}, status=400)
        binding = FieldPicklistBinding(
            app_label=app_label, model_name=model_name, field_name=field_name,
            mode=data.get("mode") or FieldPicklistBinding.Mode.FREE_TEXT,
            picklist_id=data.get("picklist") or None,
            is_required=bool(data.get("is_required")),
        )
        try:
            binding.full_clean()
            binding.save()
        except ValidationError as e:
            return _error(e)
        return JsonResponse({"id": binding.id, "message": "Binding saved"}, status=201)

    def put(self, request, id):
        try:
            binding = FieldPicklistBinding.objects.get(id=id)
        except FieldPicklistBinding.DoesNotExist:
            raise Http404("Binding not found")
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        if "mode" in data:
            binding.mode = data["mode"]
        if "picklist" in data:
            binding.picklist_id = data["picklist"] or None
        if "is_required" in data:
            binding.is_required = bool(data["is_required"])
        try:
            binding.full_clean()
            binding.save()
        except ValidationError as e:
            return _error(e)
        return JsonResponse({"message": "Binding updated"})

    def delete(self, request, id):
        try:
            binding = FieldPicklistBinding.objects.get(id=id)
        except FieldPicklistBinding.DoesNotExist:
            raise Http404("Binding not found")
        binding.delete()
        return JsonResponse({"message": "Binding deleted"})
