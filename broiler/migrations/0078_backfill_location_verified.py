"""Farms visited before the flag existed read "Pin not verified" for ever.

`location_verified` is written when a Location Capture is saved: somebody
standing at the farm, recording what their phone says. The field arrived in
0065 with `default=False` and no backfill, so every farm captured before that
kept the default while its coordinates -- copied from the same capture -- said
otherwise. The list, the Route Planner and the farm report all showed a pin
that had been confirmed on a visit as unconfirmed.

This applies each farm's latest capture to the master once, the same way
saving that capture would: the flag, the date it was taken, the accuracy, and
the pin itself where the master has drifted from it. Typing coordinates into
the master by hand is still not verification -- a farm with no capture is left
exactly as it is.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    BroilerFarm = apps.get_model("broiler", "BroilerFarm")
    FarmLocationCapture = apps.get_model("broiler", "FarmLocationCapture")

    for farm in BroilerFarm.objects.all().iterator():
        latest = (FarmLocationCapture.objects
                  .filter(farm=farm, latitude__isnull=False, longitude__isnull=False)
                  .order_by("-date", "-id").first())
        if latest is None:
            continue

        fields = []
        if farm.farm_latitude != latest.latitude:
            farm.farm_latitude = latest.latitude
            fields.append("farm_latitude")
        if farm.farm_longitude != latest.longitude:
            farm.farm_longitude = latest.longitude
            fields.append("farm_longitude")
        if farm.gps_accuracy != latest.gps_accuracy:
            farm.gps_accuracy = latest.gps_accuracy
            fields.append("gps_accuracy")
        if farm.location_captured_at != latest.date:
            farm.location_captured_at = latest.date
            fields.append("location_captured_at")
        if not farm.location_verified:
            farm.location_verified = True
            fields.append("location_verified")

        if fields:
            farm.save(update_fields=fields)


def unbackfill(apps, schema_editor):
    """Nothing to undo: the flag is only ever set, and clearing it here would
    throw away verifications made since this ran as well as the ones it
    corrected."""


class Migration(migrations.Migration):

    dependencies = [
        ("broiler", "0077_farm_capacity_optional"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
