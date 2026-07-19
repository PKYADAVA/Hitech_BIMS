# Alerts & Audit Module

A generic, reusable, production-grade CRUD **alerting** and immutable **audit
trail** for the Hitech BIMS Django project. It captures create / update / delete
/ soft-delete / restore / status-change / bulk / login / logout / password /
custom business events automatically via Django signals, with **zero per-model
wiring** for new apps.

---

## 1. Architecture at a glance

```
Request ──▶ AlertContextMiddleware ──▶ (stashes user/request in contextvar)
                                            │
Model.save()/delete() ──▶ Django signal ──▶ signals.py (thin, no logic)
                                            │  captures created? / field diff
                                            ▼
                                        handlers.py  (classifies the event)
                                            │  create / update / soft-delete /
                                            │  status-change / bulk / auth …
                                            ▼
                                        services.py  (the only place with logic)
                                        ├─ AuditService.record()  → AuditLog (immutable)
                                        └─ AlertService.create()  → Alert (feed)
                                                    │  on_commit
                                                    ▼
                                        tasks.enqueue() (Celery if present, else inline)
                                                    ▼
                                        channels.py  (DB / Log / Email / WebSocket / Slack / Teams)
```

**Design rules honoured**

* **No business logic in signals** — they only capture facts and delegate.
* **Service/registry pattern** — all writes go through `services.py`.
* **Failure isolation** — auditing never breaks the originating request
  (`process_event` and every channel are wrapped in try/except + logging).
* **Loose coupling** — models opt in through a registry/decorator or automatic
  discovery; nothing imports across app boundaries at startup.

### Folder structure

| File | Responsibility |
|------|----------------|
| `constants.py` | `Action`, `Severity`, `EventType` choices; default ignore lists |
| `conf.py` | Cached, typed accessor over `settings.ALERT_SETTINGS` |
| `context.py` | contextvar storage + `RequestSnapshot` (actor/IP/UA/session) |
| `middleware.py` | Publishes the active request into the context |
| `utils.py` | IP, user-agent parsing, value serialisation, display helpers |
| `diff.py` | Field snapshots + before/after diff (drops noise fields) |
| `registry.py` | `AlertRegistry`, `@register_alert`, autodiscovery |
| `signals.py` | pre/post_save, post_delete, m2m + auth receivers (thin) |
| `handlers.py` | Turns signal facts into `AlertEvent`s (semantics) |
| `services.py` | `AlertService`, `AuditService`, `emit_event`, templating |
| `channels.py` | Pluggable notification channels |
| `tasks.py` | Async dispatch abstraction (Celery-optional) |
| `managers.py` | `AlertableManager` for bulk-operation auditing |
| `models.py` | `Alert`, `AuditLog` |
| `permissions.py` | Row-level `scope_alerts` + DRF permission classes |
| `serializers.py` / `views.py` / `urls.py` | REST API + Alert Center page |
| `admin.py` | Admin with filters/search + CSV/XLSX export |
| `consumers.py` / `routing.py` | Optional Django Channels real-time delivery |

---

## 2. Registering models

**Nothing to do for most models.** `ALERT_SETTINGS["TRACK_ALL_MODELS"] = True`
(the default) audits every concrete model except framework noise
(`admin`, `contenttypes`, `sessions`, `migrations`, `alerts`) and anything in
`IGNORE_MODELS`. New apps are covered automatically.

**Per-model overrides** — decorate the model:

```python
from alerts.registry import register_alert
from alerts.constants import Severity

@register_alert(severity=Severity.WARNING, event_prefix="invoice", audit=True)
class Invoice(models.Model):
    ...
```

**Explicitly, from anywhere (e.g. `apps.ready`)**:

```python
from alerts.registry import registry
registry.register(MyModel, track_delete=False)
```

**Exclude a model** without turning off global tracking:

```python
ALERT_SETTINGS = {"IGNORE_MODELS": ["hr.Payslip", "inventory.StockLedgerLine"]}
```

---

## 3. Custom business events

For approvals, uploads, "document published", etc. call `emit_event`:

```python
from alerts.services import emit_event
from alerts.constants import Action, EventType

emit_event(
    action=Action.APPROVE,
    event_type=EventType.ORDER_APPROVED,
    instance=order,
    title=f"Order {order.number} approved",
    severity="success",
    metadata={"amount": str(order.total)},
)
```

Attach a **reason** (recorded on the audit row) for the change:

```python
from alerts.context import add_extra_meta
add_extra_meta(reason="Corrected on customer request")
order.status = "approved"; order.save()
```

---

## 4. Bulk operations

Django emits **no** `post_save`/`post_delete` for `bulk_create`, `bulk_update`,
`QuerySet.update()` or `QuerySet.delete()`. The only correct fix is to override
those methods, so opt a model in with `AlertableManager`:

```python
from alerts.managers import AlertableManager

class Invoice(models.Model):
    ...
    objects = AlertableManager()
```

Each bulk call then emits one summarising alert (gated by
`ENABLE_BULK_EVENTS`). Per-row diffs are intentionally omitted for bulk paths.

---

## 5. Soft delete & restore

Detected automatically from the diff — no configuration. A save that flips
`is_deleted`/`deleted`/`is_removed` **True**, or sets `deleted_at`/`date_deleted`,
becomes a `SOFT_DELETE`; the reverse becomes a `RESTORE`. Field names are
configurable in `constants.py`.

---

## 6. Notification channels

Enabled channels come from `ALERT_SETTINGS["CHANNELS"]`. Ship-safe defaults are
**Database** + **Log**. Add a channel by subclassing `BaseChannel` and listing
its dotted path:

```python
# myapp/alert_channels.py
from alerts.channels import BaseChannel

class PushChannel(BaseChannel):
    name = "push"
    def deliver(self, payload, alert=None):
        ...  # send to FCM/APNs
```

```python
ALERT_SETTINGS = {"CHANNELS": [
    "alerts.channels.DatabaseChannel",
    "alerts.channels.LogChannel",
    "myapp.alert_channels.PushChannel",
]}
```

* **Email** — `ENABLE_EMAIL=True`, set `EMAIL_RECIPIENTS` (or falls back to
  `MANAGERS`/`ADMINS`), and `EMAIL_MIN_SEVERITY` (default `error`).
* **Slack / Teams** — `ENABLE_SLACK`/`ENABLE_TEAMS=True` + the webhook URL.
* **WebSocket** — see below.

---

## 7. Real-time (WebSocket) alerts — optional

Channels is **not** a current dependency, so `consumers.py`/`routing.py` are
inert until you add it:

1. `pip install channels channels-redis`, add `"channels"` to `INSTALLED_APPS`,
   set `ASGI_APPLICATION` + `CHANNEL_LAYERS`.
2. Include `alerts.routing.websocket_urlpatterns` in your ASGI `URLRouter`.
3. `ALERT_SETTINGS["ENABLE_WEBSOCKET"] = True`.

Clients connect to `ws/alerts/`; each alert is pushed to `alerts_all` (staff)
and `alerts_user_<id>` (the actor). The navbar bell's 30s poll can then be
swapped for a socket subscription.

---

## 8. Async processing

`tasks.enqueue()` runs channel fan-out via Celery when available, else inline.
Switch behaviour with `ASYNC_BACKEND` = `"auto"` (default) / `"celery"` /
`"inline"`. Alert/Audit **rows are always written synchronously** so the feed is
immediately correct; only delivery is deferred (and fired `on_commit`).

---

## 9. REST API

Base: `/api/`. Auth: session (reuses the app login). All querysets are scoped by
`scope_alerts` (own + department + targeted-at-me; staff see all).

| Method & path | Purpose |
|---|---|
| `GET /api/alerts/` | List — filters: `severity, action, event_type, model_name, object_id, performed_by, is_read, date_from, date_to`; `search=`, `ordering=`, `page`, `page_size` |
| `GET /api/alerts/{id}/` | Detail |
| `DELETE /api/alerts/{id}/` | Delete one |
| `GET /api/alerts/unread_count/` | `{"unread": N}` |
| `POST /api/alerts/{id}/mark_read/` | Mark one read |
| `POST /api/alerts/mark_all_read/` | Mark all (in scope) read |
| `GET /api/audit-logs/` | Read-only audit trail (**staff only**) |

**UI:** a navbar bell (`templates/_alerts_bell.html`) shows the unread badge +
recent feed, and `/alerts/center/` is a full filterable notification page.

---

## 10. Configuration reference

All keys are optional; defaults live in `alerts/conf.py`.

```python
ALERT_SETTINGS = {
    "TRACK_ALL_MODELS": True,
    "IGNORE_MODELS": [],          # ["app.Model", ...]
    "IGNORE_APP_LABELS": [],      # merged with framework defaults
    "IGNORE_FIELDS": [],          # merged with updated_at/created_at/… defaults
    "ENABLE_AUDIT": True,
    "ENABLE_ALERTS": True,
    "ENABLE_BULK_EVENTS": True,
    "ENABLE_AUTH_EVENTS": True,
    "SKIP_UNCHANGED_UPDATES": True,
    "CHANNELS": ["alerts.channels.DatabaseChannel", "alerts.channels.LogChannel"],
    "ENABLE_EMAIL": False, "EMAIL_RECIPIENTS": [], "EMAIL_MIN_SEVERITY": "error",
    "ENABLE_WEBSOCKET": False,
    "ENABLE_SLACK": False, "SLACK_WEBHOOK_URL": "",
    "ENABLE_TEAMS": False, "TEAMS_WEBHOOK_URL": "",
    "ASYNC_BACKEND": "auto",
    "TEMPLATES": {},              # override message wording per Action
    "DEFAULT_PAGE_SIZE": 25,
    "MAX_DISPLAY_LENGTH": 140,
}
```

**Disable everything:** `ENABLE_ALERTS=False` and `ENABLE_AUDIT=False`, or set
`TRACK_ALL_MODELS=False` and register nothing.

**Custom message templates** (placeholders `{actor} {model} {object} {id}
{changes} {count} {title}`):

```python
ALERT_SETTINGS = {"TEMPLATES": {
    "status_change": "{actor} moved {model} {object}{changes}",
    "delete": "{actor} removed {model} {object} — heads up!",
}}
```

---

## 11. Tests

```bash
python manage.py test alerts
```

Covers units (UA parsing, IP, diff, classification, templating) and integration
(signals→alert/audit, immutability, middleware attribution, bulk, permission
scoping, and the full REST API).
