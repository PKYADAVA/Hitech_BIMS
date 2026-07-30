"""Chicks Purchase moves to a single Free % and swaps two column meanings.

Before, `rcv_qty` held the physical count (free included) and `total_qty` the
chargeable one, driven by two independent percentages. Now a single Free %
runs the line: `received_qty` is the chargeable count and `total_qty` is what
physically arrived.

The fields are renamed rather than dropped and recreated so no figure is lost
in transit, and every existing line is then recomputed from its own inputs
(Sent Qty, Free %, mortality/shortage/weaks/excess), which are untouched.
"""
from django.db import migrations, models


def recompute(apps, schema_editor):
    ChicksPurchaseItem = apps.get_model("purchase", "ChicksPurchaseItem")
    from decimal import Decimal

    def dec(value):
        return value if isinstance(value, Decimal) else Decimal(str(value or 0))

    for line in ChicksPurchaseItem.objects.all().iterator():
        factor = 1 + dec(line.free_percent) / 100
        gross = dec(line.sent_qty) * factor
        after_losses = (gross - dec(line.mortality) - dec(line.shortage)
                        - dec(line.weaks) + dec(line.excess_qty))
        line.received_qty = round(after_losses / factor)
        line.free_qty = round(dec(line.received_qty) * dec(line.free_percent) / 100)
        line.total_qty = dec(line.received_qty) + dec(line.free_qty)
        line.amount = dec(line.received_qty) * dec(line.rate)
        line.save(update_fields=["received_qty", "free_qty", "total_qty", "amount"])


def noop(apps, schema_editor):
    """Nothing to undo: the inputs were never changed, only the derived
    figures, and the reverse schema operations restore the old columns."""


class Migration(migrations.Migration):

    dependencies = [
        ("purchase", "0017_remove_creditnote_reason_remove_debitnote_reason_and_more"),
    ]

    operations = [
        # Renames first, so the stored numbers travel with their column.
        migrations.RenameField(
            model_name="chickspurchaseitem",
            old_name="sent_free_percent",
            new_name="free_percent",
        ),
        migrations.RenameField(
            model_name="chickspurchaseitem",
            old_name="rcv_qty",
            new_name="received_qty",
        ),
        migrations.RemoveField(
            model_name="chickspurchaseitem",
            name="rcv_free_percent",
        ),
        migrations.AlterField(
            model_name="chickspurchaseitem",
            name="free_percent",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=5,
                help_text="Free % on the consignment; drives Received, Free and Total"),
        ),
        migrations.AlterField(
            model_name="chickspurchaseitem",
            name="received_qty",
            field=models.DecimalField(
                decimal_places=2, default=0, editable=False, max_digits=12,
                help_text="Chargeable count — what Amount is based on"),
        ),
        migrations.RunPython(recompute, noop),
    ]
