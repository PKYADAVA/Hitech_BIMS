"""Hatchery detectors — incubation timing and hatch quality.

Scope comes from the grading's storage location where there is one. The
hatchery master carries no branch, so most of these alerts have only a
warehouse dimension; they reach whoever the rule's groups name, filtered by the
warehouse scope.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import pct, safe_url
from alerthub.scoping import rule_applies_to

from . import detector

#: How far back the timing rules look. Anything older is history, not a
#: to-do — a tray set three months ago that was never hatched is a data problem
#: for a report, not an alert to wake someone with.
WINDOW_DAYS = 45


@detector("hatchery.egg_setting_due")
def egg_setting_due(rule):
    """Graded eggs that have not been set into a setter yet."""
    from hatchery.models import EggGrading

    today = timezone.localdate()
    rows = (
        EggGrading.objects.filter(
            date__gte=today - timedelta(days=WINDOW_DAYS), tray_settings__isnull=True
        )
        .select_related("storage_location", "supplier", "item")
        .distinct()
    )

    for grading in rows:
        waiting = (today - grading.date).days
        if not compare(Decimal(waiting), rule.operator, rule.threshold):
            continue

        scope = {"warehouse": grading.storage_location}
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Egg Setting Due",
            message=(
                f"Grading {grading.transaction_no} from {grading.date:%d %b %Y} has "
                f"not been set — waiting {waiting} day(s)."
            ),
            dedupe_key=f"{rule.pk}:setting_due:{grading.pk}",
            measured_value=Decimal(waiting),
            threshold_value=rule.threshold,
            object_label="hatchery.EggGrading",
            object_id=grading.pk,
            object_display=grading.transaction_no,
            voucher_no=grading.transaction_no,
            action_url=safe_url("tray_set_list"),
            **scope,
        )


def _open_settings():
    """Tray settings with no hatch entry yet, inside the working window."""
    from hatchery.models import TraySetting

    today = timezone.localdate()
    return (
        TraySetting.objects.filter(
            setting_date__gte=today - timedelta(days=WINDOW_DAYS),
            hatch_entry__isnull=True,
        )
        .select_related("grading", "grading__storage_location", "hatchery")
    )


def _timing_rule(rule, title, date_field, describe):
    """Shared body for Transfer Due and Hatching Due.

    Both ask the same question of a different stored date: has this setting
    reached a stage it has not been recorded as passing?
    """
    today = timezone.localdate()
    for setting in _open_settings():
        due = getattr(setting, date_field, None)
        if not due or due > today:
            continue
        overdue = (today - due).days

        scope = {"warehouse": getattr(setting.grading, "storage_location", None)}
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title=title,
            message=describe(setting, due, overdue),
            dedupe_key=f"{rule.pk}:{date_field}:{setting.pk}",
            measured_value=Decimal((today - setting.setting_date).days),
            threshold_value=rule.threshold,
            object_label="hatchery.TraySetting",
            object_id=setting.pk,
            object_display=setting.setting_no,
            voucher_no=setting.setting_no,
            action_url=safe_url("hatch_entry_list") or safe_url("tray_set_list"),
            metadata={"setting_date": str(setting.setting_date),
                      "due": str(due), "days_overdue": overdue},
            **scope,
        )


@detector("hatchery.transfer_due")
def transfer_due(rule):
    _timing_rule(
        rule, "Transfer Due", "transfer_date",
        lambda s, due, overdue: (
            f"Setting {s.setting_no} was due for hatcher transfer on "
            f"{due:%d %b %Y}"
            + (f" — {overdue} day(s) ago." if overdue else " — today.")
        ),
    )


@detector("hatchery.hatching_due")
def hatching_due(rule):
    _timing_rule(
        rule, "Hatching Due", "hatch_date",
        lambda s, due, overdue: (
            f"Setting {s.setting_no} was due to hatch on {due:%d %b %Y} and has no "
            f"hatch entry"
            + (f" — {overdue} day(s) late." if overdue else " — due today.")
        ),
    )


def _recent_hatches():
    from hatchery.models import HatchEntry

    since = timezone.localdate() - timedelta(days=WINDOW_DAYS)
    return (
        HatchEntry.objects.filter(hatch_date__gte=since, eggs_total__gt=0)
        .select_related("tray_setting", "tray_setting__grading",
                        "tray_setting__grading__storage_location")
        .prefetch_related("hatcher_outputs")
    )


def _hatch_scope(entry):
    grading = getattr(entry.tray_setting, "grading", None)
    return {"warehouse": getattr(grading, "storage_location", None)}


@detector("hatchery.poor_hatchability")
def poor_hatchability(rule):
    """Saleable chicks as a share of eggs set."""
    for entry in _recent_hatches():
        rate = pct(entry.chicks_total, entry.eggs_total)
        if rate is None:
            continue
        if not compare(rate, rule.operator, rule.threshold):
            continue

        scope = _hatch_scope(entry)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Poor Hatchability",
            message=(
                f"Hatch {entry.transaction_no} yielded {int(entry.chicks_total):,} "
                f"chicks from {int(entry.eggs_total):,} eggs — {rate:.1f}% "
                f"(target {rule.threshold}%)."
            ),
            dedupe_key=f"{rule.pk}:hatchability:{entry.pk}",
            measured_value=round(rate, 3),
            threshold_value=rule.threshold,
            object_label="hatchery.HatchEntry",
            object_id=entry.pk,
            object_display=entry.transaction_no,
            voucher_no=entry.transaction_no,
            action_url=safe_url("hatch_entry_list"),
            **scope,
        )


@detector("hatchery.low_chick_output")
def low_chick_output(rule):
    """Absolute saleable-chick count from one hatch."""
    for entry in _recent_hatches():
        if not compare(entry.chicks_total, rule.operator, rule.threshold):
            continue

        scope = _hatch_scope(entry)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="Low Chick Output",
            message=(
                f"Hatch {entry.transaction_no} produced only "
                f"{int(entry.chicks_total):,} saleable chicks "
                f"(expected at least {rule.threshold})."
            ),
            dedupe_key=f"{rule.pk}:chick_output:{entry.pk}",
            measured_value=entry.chicks_total,
            threshold_value=rule.threshold,
            object_label="hatchery.HatchEntry",
            object_id=entry.pk,
            object_display=entry.transaction_no,
            voucher_no=entry.transaction_no,
            action_url=safe_url("hatch_entry_list"),
            **scope,
        )


@detector("hatchery.high_reject")
def high_reject(rule):
    """Culls, malformed and dead-in-shell as a share of eggs set.

    Summed across the hatchers of one entry. An entry whose hatcher breakdown
    was never filled in is skipped — zero rejects recorded is not evidence of
    zero rejects.
    """
    for entry in _recent_hatches():
        outputs = list(entry.hatcher_outputs.all())
        if not outputs:
            continue

        rejects = sum(
            (o.culls_malf_qty or 0) + (o.dead_in_shell_qty or 0) for o in outputs
        )
        share = pct(rejects, entry.eggs_total)
        if share is None:
            continue
        if not compare(share, rule.operator, rule.threshold):
            continue

        scope = _hatch_scope(entry)
        if not rule_applies_to(rule, **scope):
            continue

        raise_alert(
            rule,
            title="High Reject %",
            message=(
                f"Hatch {entry.transaction_no} rejected {rejects:,} of "
                f"{int(entry.eggs_total):,} eggs set — {share:.1f}% "
                f"(limit {rule.threshold}%)."
            ),
            dedupe_key=f"{rule.pk}:reject:{entry.pk}",
            measured_value=round(share, 3),
            threshold_value=rule.threshold,
            object_label="hatchery.HatchEntry",
            object_id=entry.pk,
            object_display=entry.transaction_no,
            voucher_no=entry.transaction_no,
            action_url=safe_url("hatch_entry_list"),
            metadata={"rejects": rejects},
            **scope,
        )
