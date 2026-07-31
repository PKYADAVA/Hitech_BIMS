"""Running the configured rules.

One entry point, :func:`scan`, which the management command and any scheduler
call. It walks the active rules, hands each to its detector, and reports what
was raised.

**Every rule is isolated.** A detector that raises — a renamed field, a missing
related row — must not stop the twenty rules after it. Each is wrapped, the
traceback is logged, and the scan carries on. A scan that dies halfway through
is worse than one that skips a rule, because the rules that never ran leave no
trace of not having run.

**Counting is done here, not by detectors.** The scan measures how many
notifications appeared while a rule ran rather than trusting a return value, so
a detector cannot over-report, and alerts suppressed by the cooldown are counted
as suppressed rather than raised.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .catalog import BY_KEY
from .models import AlertRule, Notification
from . import detectors

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    """What one scan did, in enough detail to explain a quiet feed."""

    raised: int = 0
    rules_run: int = 0
    skipped_unsupported: list = field(default_factory=list)
    skipped_no_detector: list = field(default_factory=list)
    failed: list = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.raised} alert(s) from {self.rules_run} rule(s)"]
        if self.skipped_unsupported:
            parts.append(f"{len(self.skipped_unsupported)} awaiting a data source")
        if self.skipped_no_detector:
            parts.append(f"{len(self.skipped_no_detector)} with no detector")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        return "; ".join(parts)


def scan(*, rule_key=None, rule_id=None, dry_run=False) -> ScanResult:
    """Evaluate active alert rules and raise whatever they find.

    ``rule_key`` / ``rule_id`` narrow the run to one catalogue key or one
    configured rule, which is how you test a threshold without waiting for the
    schedule. ``dry_run`` resolves and reports the rules without calling any
    detector — it answers "what would run", not "what would fire", because
    finding out what would fire means doing the work.
    """
    detectors.autodiscover()

    rules = AlertRule.objects.filter(is_active=True).prefetch_related(
        "notify_groups", "notify_branches", "notify_org_centres",
        "notify_farms", "notify_warehouses",
    )
    if rule_key:
        rules = rules.filter(rule_key=rule_key)
    if rule_id:
        rules = rules.filter(pk=rule_id)

    result = ScanResult()

    for rule in rules:
        spec = BY_KEY.get(rule.rule_key)
        if spec is None:
            result.skipped_no_detector.append(rule.rule_key)
            logger.warning("alerthub: rule %s has an unknown key %r",
                           rule.pk, rule.rule_key)
            continue
        if not spec.supported:
            result.skipped_unsupported.append(rule.rule_key)
            continue

        run = detectors.get(rule.rule_key)
        if run is None:
            # The catalogue says this fires but nothing implements it — a
            # wiring bug, and louder than a missing data source.
            result.skipped_no_detector.append(rule.rule_key)
            logger.error("alerthub: no detector registered for %r", rule.rule_key)
            continue

        if dry_run:
            result.rules_run += 1
            continue

        before = Notification.objects.count()
        try:
            run(rule)
        except Exception:
            logger.exception("alerthub: detector %r failed for rule %s",
                             rule.rule_key, rule.pk)
            result.failed.append(rule.rule_key)
            continue

        result.rules_run += 1
        result.raised += Notification.objects.count() - before

    return result
