"""Carry each group's Receivables & Payables choice onto the two widgets.

The single "balances" widget became "receivables" and "payables". A widget with
no stored row is hidden, so without this every group that had configured the
dashboard would simply lose the card — not see two, see none — and the cause
would look like a bug in the new widgets rather than a rename.

The old row's position is kept for receivables and payables follows it, which
is the order they were in inside the combined card.
"""
from django.db import migrations


def split(apps, schema_editor):
    Widget = apps.get_model("user", "GroupDashboardWidget")
    for row in Widget.objects.filter(widget_key="balances"):
        for key, offset in (("receivables", 0), ("payables", 1)):
            Widget.objects.update_or_create(
                group_id=row.group_id,
                widget_key=key,
                defaults={"enabled": row.enabled, "position": row.position + offset},
            )
    Widget.objects.filter(widget_key="balances").delete()


def rejoin(apps, schema_editor):
    """Back to one row, taking receivables' setting as the pair's."""
    Widget = apps.get_model("user", "GroupDashboardWidget")
    for row in Widget.objects.filter(widget_key="receivables"):
        Widget.objects.update_or_create(
            group_id=row.group_id,
            widget_key="balances",
            defaults={"enabled": row.enabled, "position": row.position},
        )
    Widget.objects.filter(widget_key__in=["receivables", "payables"]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0013_userprofile_individual_permissions_usertabpermission"),
    ]

    operations = [migrations.RunPython(split, rejoin)]
