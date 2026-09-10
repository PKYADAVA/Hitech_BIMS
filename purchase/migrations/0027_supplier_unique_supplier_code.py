"""Make the supplier code unique — minted by next_code(), never typed.

The same shape as the customer code: two saves reading one maximum take the
same SUP-NNNN. Partial for the same reason too — a blank code is allowed, and
'' is a value to Postgres.
"""

import re

from django.db import migrations, models

def renumber_duplicate_codes(apps, schema_editor):
    """Give any repeated code a fresh one before the constraint is created.

    This runs as part of a PRE_DEPLOY job: a constraint that cannot be created
    fails the job and blocks the deploy, so arriving with the duplicates
    already resolved is better than arriving and stopping. On a database with
    none — which is every one we can see — it does nothing.

    Oldest first, so the record that has carried the code longest keeps it:
    that is the one already printed on things.
    """
    Model = apps.get_model("purchase", "Supplier")
    prefix = "SUP-"
    seen, clashes, highest = set(), [], 0
    for row in Model.objects.order_by("id").values("id", "code"):
        code = row["code"]
        if not code:
            continue
        match = re.match(r"^%s(\d+)$" % re.escape(prefix), code)
        if match:
            highest = max(highest, int(match.group(1)))
        if code in seen:
            clashes.append(row["id"])
        else:
            seen.add(code)
    for pk in clashes:
        while True:
            highest += 1
            fresh = "%s%04d" % (prefix, highest)
            if fresh not in seen:
                break
        seen.add(fresh)
        Model.objects.filter(pk=pk).update(code=fresh)


def keep(apps, schema_editor):
    """Nothing to undo: a renumbered record's code is as valid as the one it
    replaced, and restoring the clash would be the wrong direction."""


class Migration(migrations.Migration):

    dependencies = [
        ('purchase', '0026_alter_generalpurchase_calculation_based_on'),
    ]

    operations = [
        migrations.RunPython(renumber_duplicate_codes, keep),
        migrations.AddConstraint(
            model_name='supplier',
            constraint=models.UniqueConstraint(condition=models.Q(('code', ''), _negated=True), fields=('code',), name='unique_supplier_code'),
        ),
    ]
