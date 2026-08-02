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


#: What each surface's recorded keys and fields mean, so one revert serves all
#: three: ``(model, key field, field prefix)``.
#:
#: The prefix matters. Web and dashboard entries record model field names, but
#: mobile entries record *action* names ("edit"), because that is what the
#: matrix and the API speak. Without the mapping every mobile revert silently
#: set nothing — the attribute it looked for did not exist.
#:
#: Models are looked up lazily to keep this module import-light.
#: ``membership`` is absent on purpose: it records who joined or left a group,
#: which is not a row of fields to put back.
REVERTABLE = {
    "web": ("user.GroupTabPermission", "tab_code", ""),
    "mobile": ("user.GroupMobileTabPermission", "tab_code", "can_"),
    "mobile_module": ("user.GroupMobileAccess", "module_key", ""),
    "dashboard": ("user.GroupDashboardWidget", "widget_key", ""),
}


def revert(request, entry):
    """Put back the "before" side of a recorded change.

    Undo is cheap here only because the log already stores both sides — this
    walks the diff backwards rather than replaying history.

    Two rules it does not bend. The revert is itself recorded, as a new entry
    rather than by deleting the old one: an audit trail that can erase its own
    rows answers a different, weaker question. And it writes the same tables
    the editors write, so every gate downstream still applies — reverting a
    Mobile Access change cannot restore access the web matrix has since
    withdrawn.

    Returns the number of rows restored, or raises ValueError when the entry
    is not one this can undo.
    """
    from django.apps import apps

    target = REVERTABLE.get(entry.surface)
    if target is None:
        raise ValueError(f"{entry.get_surface_display()} changes cannot be reverted.")

    changes = (entry.detail or {}).get("changes") or {}
    if not changes:
        raise ValueError("This entry recorded no change to undo.")

    label, key_field, prefix = target
    model = apps.get_model(label)

    restored = 0
    for key, fields in changes.items():
        before = {f"{prefix}{field}": was for field, (was, _now) in fields.items()}

        # Every "before" being None means the row did not exist. Recreating it
        # with nulls is not the state we are restoring — and would not even
        # save, since these columns are NOT NULL.
        if all(value is None for value in before.values()):
            model.objects.filter(group=entry.group, **{key_field: key}).delete()
            restored += 1
            continue

        row, _created = model.objects.get_or_create(
            group=entry.group, **{key_field: key})
        for field, value in before.items():
            # A field the model no longer has, or one absent from this entry —
            # the registry moved on since it was written. Leave the model's
            # own default rather than failing the whole revert.
            if value is not None and hasattr(row, field):
                setattr(row, field, value)
        row.save()
        restored += 1

    # Web rows with nothing ticked are stored as absent, not as a row of
    # falses; leaving an all-false row behind would read as "configured".
    if entry.surface == "web":
        for key in changes:
            row = model.objects.filter(group=entry.group, **{key_field: key}).first()
            if row and not any(getattr(row, f"can_{a}", False)
                               for a in ("view", "add", "edit", "delete",
                                         "print", "save", "update", "favorite")):
                row.delete()

    log_change(
        request, entry.group, entry.surface,
        f"Reverted: {entry.summary}",
        {"changes": {k: {f: [now, was] for f, (was, now) in v.items()}
                     for k, v in changes.items()},
         "reverted_entry": entry.id},
    )
    return restored


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
