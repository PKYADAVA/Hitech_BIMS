"""One batch/flock number per hatch setting.

`batch_flock_no` is generated as DDMM plus that day's sequence — 0806/01,
0806/02 — by reading the highest issued today and adding one. Two settings
filed in the same moment both read that highest and both become 0806/01, and
the number stops telling one batch from another.

The constraint is partial, and that is not a detail: the column is written
empty by the first save and filled by a second, so for a moment every new
setting holds ''. Postgres treats '' as a value, so a plain unique index would
admit one and refuse every setting created alongside it — breaking the
ordinary case to guard against the rare one.
"""

import re

from django.db import migrations, models


def renumber_duplicate_numbers(apps, schema_editor):
    """Give any repeated number a fresh one before the constraint exists.

    Runs as part of a PRE_DEPLOY job: a constraint that cannot be created
    fails the job and blocks the deploy.
    """
    HatchSetting = apps.get_model("hatchery", "HatchSetting")
    seen, clashes = set(), []
    # Oldest first, so the setting that has carried the number longest keeps it.
    for row in HatchSetting.objects.order_by("id").values("id", "batch_flock_no"):
        number = row["batch_flock_no"]
        if not number:
            continue
        if number in seen:
            clashes.append((row["id"], number))
        else:
            seen.add(number)
    for pk, number in clashes:
        match = re.match(r"^(\d{4}/)(\d+)$", number)
        if not match:
            continue                # not a number this scheme issued; leave it
        prefix, n = match.group(1), int(match.group(2))
        while True:
            n += 1
            fresh = "%s%02d" % (prefix, n)
            if fresh not in seen:
                break
        seen.add(fresh)
        HatchSetting.objects.filter(pk=pk).update(batch_flock_no=fresh)


def keep(apps, schema_editor):
    """Nothing to undo: the renumbered settings keep their new numbers, which
    are as valid as the ones they replaced."""


class Migration(migrations.Migration):

    dependencies = [
        ('hatchery', '0027_alter_chicksale_payment_mode_and_more'),
    ]

    operations = [
        migrations.RunPython(renumber_duplicate_numbers, keep),
        migrations.AddConstraint(
            model_name='hatchsetting',
            constraint=models.UniqueConstraint(condition=models.Q(('batch_flock_no', ''), _negated=True), fields=('batch_flock_no',), name='unique_hatch_setting_batch_flock_no'),
        ),
    ]
