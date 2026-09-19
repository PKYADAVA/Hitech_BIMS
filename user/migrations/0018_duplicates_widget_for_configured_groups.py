"""Give the Duplicate Entries card to groups whose dashboard was set by hand.

A group that never chose its widgets gets the default list, which already
carries the card. A group that did (Managers) has only the rows saved at the
time, from before the card existed, so it never appeared for them. This adds
it, enabled, just before Field Team — where the default order puts it — or at
the end when the group has no Field Team row. The card still shows only to
people who can open Duplicate Entries.
"""
from django.db import migrations


def add_duplicates_card(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Widget = apps.get_model("user", "GroupDashboardWidget")
    for group in Group.objects.filter(dashboard_widgets__isnull=False).distinct():
        rows = Widget.objects.filter(group=group)
        if rows.filter(widget_key="duplicates").exists():
            continue
        field_team = rows.filter(widget_key="field_team").first()
        if field_team:
            at = field_team.position
            for row in rows.filter(position__gte=at):
                row.position += 1
                row.save(update_fields=["position"])
        else:
            at = max(rows.values_list("position", flat=True), default=0) + 1
        Widget.objects.create(group=group, widget_key="duplicates", enabled=True, position=at)


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0017_duplicate_dismissal"),
    ]

    operations = [
        migrations.RunPython(add_duplicates_card, migrations.RunPython.noop),
    ]
