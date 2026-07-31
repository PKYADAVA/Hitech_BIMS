"""System detectors — disk, failed logins and refused requests.

These are the only rules whose subject is the ERP itself rather than the
business, so they carry no branch, farm or warehouse: there is nothing to scope
a full disk to. They reach the groups the rule names, which should be a small
administrative one.
"""
from __future__ import annotations

import shutil
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from alerthub.constants import compare
from alerthub.engine import raise_alert
from alerthub.measures import safe_url

from . import detector


@detector("system.storage_low")
def storage_low(rule):
    """Free space on the volume holding the project.

    Measured with ``shutil.disk_usage`` rather than by asking PostgreSQL,
    because the database may live on another host while the thing that fills up
    first is usually this one — media uploads and log files.
    """
    try:
        usage = shutil.disk_usage(str(settings.BASE_DIR))
    except OSError:
        return                             # unreadable path is not an alert

    free_pct = Decimal(usage.free) / Decimal(usage.total) * 100
    if not compare(free_pct, rule.operator, rule.threshold):
        return

    gb = lambda n: n / (1024 ** 3)         # noqa: E731 - local formatting helper
    raise_alert(
        rule,
        title="Database Storage Low",
        message=(
            f"{free_pct:.1f}% free on the application volume — "
            f"{gb(usage.free):.1f} GB of {gb(usage.total):.1f} GB "
            f"(limit {rule.threshold}%)."
        ),
        dedupe_key=f"{rule.pk}:storage_low",
        measured_value=round(free_pct, 3),
        threshold_value=rule.threshold,
        object_label="system.Storage",
        object_display="Application volume",
        metadata={"free_gb": f"{gb(usage.free):.1f}",
                  "total_gb": f"{gb(usage.total):.1f}"},
    )


@detector("system.login_failed")
def login_failed(rule):
    """Repeated failed logins for one account in the last hour.

    Reads the audit trail's auth events (``alerts.Alert``) rather than the log
    file. The log is a rotating 1 MB file written by several processes and
    drops records under load, so counting failures from it would understate
    exactly the burst this rule exists to catch.
    """
    from alerts.models import Alert

    since = timezone.now() - timedelta(hours=1)
    bursts = (
        Alert.objects.filter(event_type="login_failed", created_at__gte=since)
        .values("actor_label")
        .annotate(attempts=Count("id"))
    )

    for burst in bursts:
        attempts = Decimal(burst["attempts"])
        if not compare(attempts, rule.operator, rule.threshold):
            continue

        who = burst["actor_label"] or "an unknown account"
        raise_alert(
            rule,
            title="Login Failed",
            message=(
                f"{int(attempts)} failed login attempts for {who} in the last hour "
                f"(limit {rule.threshold})."
            ),
            dedupe_key=f"{rule.pk}:login_failed:{who}:"
                       f"{timezone.now():%Y-%m-%d-%H}",
            measured_value=attempts,
            threshold_value=rule.threshold,
            object_label="auth.User",
            object_display=who,
            metadata={"account": who, "attempts": int(attempts)},
        )


@detector("system.unauthorized_login")
def unauthorized_login(rule):
    """Requests the Web-Access matrix refused.

    Only ``denied`` verdicts. ``WebAccessAudit`` also records ``unmapped`` rows,
    which are urls no tab claims yet — a configuration to-do, not an intrusion,
    and there are dozens of them. Alerting on those would bury the handful of
    real refusals.
    """
    from user.models import WebAccessAudit

    since = timezone.now() - timedelta(hours=24)
    rows = WebAccessAudit.objects.filter(
        verdict=WebAccessAudit.DENIED, last_seen__gte=since
    )

    for row in rows:
        raise_alert(
            rule,
            title="Unauthorized Access Attempt",
            message=(
                f"{row.username} was refused {row.method} {row.url_name}"
                + (f" ({row.tab_code})" if row.tab_code else "")
                + f" — {row.hits} time(s), last {row.last_seen:%d %b %Y %H:%M}."
            ),
            dedupe_key=f"{rule.pk}:denied:{row.pk}:{row.last_seen:%Y-%m-%d-%H}",
            measured_value=Decimal(row.hits),
            object_label="user.WebAccessAudit",
            object_id=row.pk,
            object_display=f"{row.method} {row.url_name}",
            # WebAccessAudit has no page of its own — it is read from the admin
            # and the webaccess_audit command — so there is nowhere to send a
            # View button. Better no button than one that 404s.
            action_url="",
            metadata={"username": row.username, "path": row.path,
                      "tab_code": row.tab_code, "hits": row.hits},
        )
