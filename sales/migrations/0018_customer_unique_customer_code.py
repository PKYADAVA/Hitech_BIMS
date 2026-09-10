"""Make the customer code unique — it is minted, never typed.

Customer.next_code() reads the highest CUST-NNNN and adds one, so two saves
landing together take the same number. A code that identifies two parties
identifies neither.

The constraint is partial. The code may legitimately be blank, and Postgres
treats '' as a value — a plain unique index would admit the first blank and
refuse every one after it.
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
    Model = apps.get_model("sales", "Customer")
    prefix = "CUST-"
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
        ('sales', '0017_alter_customer_phone'),
    ]

    operations = [
        migrations.RunPython(renumber_duplicate_codes, keep),
        migrations.AddConstraint(
            model_name='customer',
            constraint=models.UniqueConstraint(condition=models.Q(('code', ''), _negated=True), fields=('code',), name='unique_customer_code'),
        ),
    ]
