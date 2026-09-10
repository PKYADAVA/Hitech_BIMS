"""One unit number per shed, within its farm.

`unit_no` is the running 1, 2, 3… a farm's sheds are known by, assigned in
save() as "the highest on this farm, plus one". Two sheds added to one farm in
the same moment both read that highest, and the farm ends up with two Shed 2 —
which also names them, since shed_name is built from the number.

Scoped to the farm, not global: Shed 1 exists on every farm and should. And
excluding 0, the field's default, so several sheds that never went through
save() are not treated as a clash.

`shed_no` is deliberately left alone: despite the name it is a legacy
free-text identifier mirroring shed_name, so repeats there are ordinary.
"""

from django.db import migrations, models


def renumber_duplicate_units(apps, schema_editor):
    """Give any repeated unit number a fresh one before the constraint exists.

    Runs as part of a PRE_DEPLOY job: a constraint that cannot be created
    fails the job and blocks the deploy. On a database with no duplicates —
    which is every one we can see — this does nothing.
    """
    BroilerFarmShed = apps.get_model("broiler", "BroilerFarmShed")
    highest, taken, clashes = {}, set(), []
    # Oldest first, so the shed that has answered to the number longest keeps it.
    for row in BroilerFarmShed.objects.order_by("id").values("id", "farm_id", "unit_no"):
        farm, unit = row["farm_id"], row["unit_no"] or 0
        highest[farm] = max(highest.get(farm, 0), unit)
        if unit and (farm, unit) in taken:
            clashes.append((row["id"], farm))
        else:
            taken.add((farm, unit))
    for pk, farm in clashes:
        highest[farm] = highest.get(farm, 0) + 1
        taken.add((farm, highest[farm]))
        BroilerFarmShed.objects.filter(pk=pk).update(unit_no=highest[farm])


def keep(apps, schema_editor):
    """Nothing to undo: a renumbered shed's number is as good as the one it
    replaced, and restoring the clash would be the wrong direction."""


class Migration(migrations.Migration):

    dependencies = [
        ('broiler', '0071_alter_gcpostingsettings_cutoff_date_and_more'),
    ]

    operations = [
        migrations.RunPython(renumber_duplicate_units, keep),
        migrations.AddConstraint(
            model_name='broilerfarmshed',
            constraint=models.UniqueConstraint(condition=models.Q(('unit_no', 0), _negated=True), fields=('farm', 'unit_no'), name='unique_shed_unit_no_per_farm'),
        ),
    ]
