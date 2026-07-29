"""Sample-template download for every django-import-export admin Import page.

Every model registered with ``ImportExportModelAdmin`` shows an *Import* button.
This adds "Download sample template" links to that page and serves the template
— a file whose columns are the model resource's own import columns, so a bulk
upload can populate every field — in Excel (.xlsx) or CSV.

One view + one template covers every module because the columns are derived from
each model's resource at request time; nothing is hand-maintained per model.
"""

import csv

import tablib
from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponse
from import_export.admin import ImportMixin

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@staff_member_required
def admin_import_template(request):
    """Blank import template (header row = every import column) for the model
    named by ``?app=&model=``. ``?format=xlsx`` (default) or ``csv``."""
    app_label = (request.GET.get("app") or "").strip()
    model_name = (request.GET.get("model") or "").strip()
    fmt = (request.GET.get("format") or "xlsx").strip().lower()

    model_admin = None
    for model, registered_admin in admin.site._registry.items():
        if (model._meta.app_label == app_label
                and model._meta.model_name == model_name):
            model_admin = registered_admin
            break

    if model_admin is None or not isinstance(model_admin, ImportMixin):
        raise Http404("No importable admin is registered for that model.")

    resource_class = model_admin.get_import_resource_classes(request)[0]
    headers = resource_class().get_export_headers()  # every importable column
    filename = f"{app_label}_{model_name}_import_template"

    if fmt == "csv":
        # utf-8-sig (BOM) so Excel reliably splits it into separate columns.
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="{filename}.csv"'
        response.write("﻿")
        csv.writer(response).writerow(headers)
        return response

    # Excel: a real spreadsheet with each column in its own cell.
    dataset = tablib.Dataset(headers=headers)
    response = HttpResponse(dataset.export("xlsx"), content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}.xlsx"'
    return response


# Route every import-export admin through our template (which injects the
# download links). Subclasses that don't set their own import_template_name
# inherit this, so the links appear on every module's Import page.
ImportMixin.import_template_name = "admin_custom/import_with_sample.html"
