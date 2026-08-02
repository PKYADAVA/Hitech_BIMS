"""Recording who changed someone's access, and to what.

``WebAccessAudit`` records what the guard *refused*. Nothing recorded what an
administrator *granted*, so the obvious question after a support call — "who
turned Sales off for Managers, and when?" — had no answer anywhere. Every
access editor now writes one row per save through :func:`log_change`.

Kept deliberately dumb: a summary line an administrator can read, plus the
before/after of only the keys that actually moved. A full snapshot of every
save would be unreadable within a week, and a bare diff is meaningless once the
registry changes underneath it.

Logging must never be the reason a save fails, so every call is wrapped.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def diff_flags(before: dict, after: dict) -> dict:
    """``{key: [was, now]}`` for the keys whose value changed."""
    keys = set(before) | set(after)
    return {k: [before.get(k), after.get(k)]
            for k in sorted(keys) if before.get(k) != after.get(k)}


def diff_matrix(before: dict, after: dict) -> dict:
    """Same, one level deeper: ``{tab: {action: [was, now]}}``.

    Used by the screen matrices, where a value is itself a dict of actions.
    """
    out = {}
    for tab in sorted(set(before) | set(after)):
        moved = diff_flags(before.get(tab) or {}, after.get(tab) or {})
        if moved:
            out[tab] = moved
    return out


def log_change(request, group, surface, summary, detail=None, source="web"):
    """Record one access change. Never raises."""
    from user.models import AccessChangeLog

    try:
        user = getattr(request, "user", None)
        AccessChangeLog.objects.create(
            surface=surface,
            group=group,
            changed_by=(user.get_username() if user and user.is_authenticated
                        else "system"),
            summary=summary[:300],
            detail=detail or {},
            source=source,
        )
    except Exception:
        logger.exception("access log: could not record %s change for %s",
                         surface, getattr(group, "name", group))


def snapshot(rows, key_field, fields):
    """``{key: {field: value}}`` from model rows — one surface's current state.

    Every editor stores a row per thing with a handful of columns, so one
    reader serves all three and the three diffs become comparable.
    """
    return {
        getattr(row, key_field): {f: getattr(row, f) for f in fields}
        for row in rows
    }


def record_save(request, group, surface, before, after, labels=None,
                noun="screen", extra="", source="web"):
    """Diff two snapshots and record the change. Never raises.

    This is the one place a save is written to the log, so a fourth editor
    gets an audit trail by calling it rather than by remembering to. It also
    means the three surfaces phrase their entries the same way, which matters
    when they are read together on one page.
    """
    moved = diff_matrix(before, after)
    summary = describe_matrix_change(moved, labels, noun)
    if extra:
        summary = f"{summary}; {extra}"
    log_change(request, group, surface, summary, {"changes": moved}, source)
    return moved


def describe_matrix_change(moved: dict, labels: dict | None = None,
                           noun: str = "screen") -> str:
    """A one-line summary of a matrix diff, e.g. "3 screens changed: …".

    Names the first few so the list is scannable without opening the detail.
    """
    if not moved:
        return "No change"
    labels = labels or {}
    names = [labels.get(tab, tab) for tab in list(moved)[:3]]
    tail = "" if len(moved) <= 3 else f" and {len(moved) - 3} more"
    word = noun if len(moved) == 1 else f"{noun}s"
    return f"{len(moved)} {word} changed: {', '.join(names)}{tail}"
