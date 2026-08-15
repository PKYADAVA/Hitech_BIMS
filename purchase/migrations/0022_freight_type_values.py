"""Move the two old freight types onto the three new ones.

The labels are mapped by what somebody meant when they picked them:
"Included in Bill" -> "Freight Included", "Extra" -> "Freight Extra".

The arithmetic behind them was the other way round. The old code added the
freight when the type was "Included in Bill" and left it out when it was
"Extra" — the opposite of what those words say, and the reason this is being
straightened out. Stored net_amount values are left exactly as they are: a
document that has been issued keeps the total it was issued with. Only a
re-save recomputes, and then it recomputes correctly.
"""
from django.db import migrations

MAP = {"Included in Bill": "Freight Included", "Extra": "Freight Extra"}


def forwards(apps, schema_editor):
    for name in ("GeneralPurchase", "ChicksPurchase"):
        model = apps.get_model("purchase", name)
        for old, new in MAP.items():
            model.objects.filter(freight_type=old).update(freight_type=new)


def backwards(apps, schema_editor):
    reverse = {v: k for k, v in MAP.items()}
    for name in ("GeneralPurchase", "ChicksPurchase"):
        model = apps.get_model("purchase", name)
        for new, old in reverse.items():
            model.objects.filter(freight_type=new).update(freight_type=old)
        # "No Freight" had no equivalent before; it becomes the type that also
        # left the bill alone.
        model.objects.filter(freight_type="No Freight").update(freight_type="Extra")


class Migration(migrations.Migration):

    dependencies = [("purchase", "0021_alter_chickspurchase_freight_type_and_more")]

    operations = [migrations.RunPython(forwards, backwards)]
