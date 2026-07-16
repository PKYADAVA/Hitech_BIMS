# Employee Tracking Module — Phase 1 Analysis Report

Analysis of the existing Hitech BIMS ERP as the foundation for the Employee
Tracking module (TrackoLap integration via a provider-agnostic layer).
No code has been written yet; this document records what exists, which
patterns the new module must follow, and the decisions that need sign-off
before Phase 2 (Database).

---

## 1. Folder Structure & App Conventions

Django 4.2.6 monolith. Each domain is a root-level app (`broiler`, `hatchery`,
`inventory`, `hr`, `sales`, `purchase`, `account`, `user`, `notification`,
`environmental_monitoring`), registered in `INSTALLED_APPS` and included at
root path (`""`) in `Hitech_BIMS/urls.py`. Every app owns:

- `models.py`, `views.py`, `urls.py`, `admin.py`, `templates/` (flat, no
  app-namespace subfolder), optional `services/`, `management/commands/`,
  `conf.py`, `validation.py`, `templatetags/`.
- The two most mature apps (`account`, `environmental_monitoring`,
  `notification`) use a **service layer** (`services/*.py`) that views call
  into; external systems are wrapped in a single client module
  (`environmental_monitoring/services/tapo_client.py` is the only file that
  imports `kasa`).

**Implication:** the tracking module should be a new root-level app
(proposed name: `tracking`, verbose "Employee Tracking") with the same
anatomy — models / services / providers / management commands / templates /
urls — not code bolted into `hr`.

## 2. Authentication

- Django session auth only. `LOGIN_URL=/login/`, post-login `/`,
  post-logout `/login/`. Views use `@login_required(login_url="login")`
  (function views) or `@method_decorator(login_required)` (class views).
- Sessions: 8h age, expire at browser close, `SESSION_SAVE_EVERY_REQUEST`.
- **DRF is listed in `requirements.txt` but never imported anywhere.** All
  "API" endpoints are plain `django.views.View` classes / functions returning
  `JsonResponse`. Names like `EmployeeAttendanceListAPIView` are conventions,
  not DRF. The tracking APIs must follow this same plain-Django JSON pattern.

## 3. Authorization (Web-Access matrix)

Single source of truth: `user/access.py`.

- `MODULE_REGISTRY` = Module (navbar) → Section → Tab, where each tab code
  **is** the primary Django URL name. Extra url-names (e.g. `api_*`) attach to
  a tab via the optional 3rd tuple item so the middleware guards them too.
- 8 actions per tab (`view/add/edit/delete/print/save/update/favorite`) stored
  on `GroupTabPermission` per Django `Group`; `GroupAccessProfile(access_type
  ="admin")` and superusers bypass.
- Enforced server-side by `user.middleware.WebAccessMiddleware`
  (`process_view` resolves url-name → tab → action); nav/section/tab hiding is
  driven by `user.context_processors.web_access` exposing `allowed_nav`,
  `allowed_sections`, `allowed_tabs`, `section_url`, `page_perms`.

**Implication:** registering the tracking screens = adding a new section (or
sections) under the existing `hr` nav in `MODULE_REGISTRY`, plus entries in
`templates/_subnav.html` and `templates/main_top_navbar.html`. Permissions,
nav-hiding, and middleware enforcement then come for free. API url-names go in
the tab's `extra_urls`.

## 4. HR / Employee / Attendance Modules

`hr/models.py`:

- `Employee` — `OneToOneField(User)` (nullable), random unique 5-digit
  `employee_id`, `full_name`, `image` (`employee_images/`), FK `Designation`,
  FK `inventory.Warehouse` (acts as the location/branch anchor), FK hr
  `Group`. **There is no Branch or Department model in HR** — organisational
  filtering today means Warehouse / Group / Designation. (Broiler has its own
  `Branch`, but it is a farm-network concept, not an employee org unit.)
- `Attendance` — `employee`, `date`, `check_in_time`, `check_out_time`,
  `status` (Present/Absent/On Leave/First Half/Second Half). **No GPS, no
  photo, no approval fields.** Payroll consumes it via
  `Payroll.calculate_total_working_days()`.
- `EmployeeLeave` + `LeaveSelectedDate` (leave requests, approved dates).

**Implication for attendance integration:** GPS check-in/out must *extend*
`Attendance` (a linked `tracking` model keyed to the same `employee` + `date`,
writing `check_in_time`/`check_out_time` through the existing model) rather
than replace it — payroll math must keep working untouched.

## 5. Dashboard & UI Stack

- `user/views.py: dashboard/home` is the landing page; module pages extend
  `templates/base.html`.
- Frontend: **Bootstrap 5 (local)** + jQuery 3.7 + DataTables (+ buttons,
  responsive) + Select2 + Toastify + Font Awesome 6 + Poppins, mostly from
  CDNs; global styles in `static/css/style.css`.
- `static/js/main.js` auto-upgrades every `select.form-select` to Select2
  site-wide (MutationObserver + event bridge). **Never add per-page Select2
  init.** Cache-busted via `?v=` query.
- Blocks available: `title / css / nav / body / content / js`. Subnavs render
  through the shared `templates/_subnav.html` keyed by `module`, guarded by
  `allowed_tabs`.
- **No map library exists anywhere in the project today.**

## 6. Database

- PostgreSQL via psycopg3; `DEFAULT_AUTO_FIELD=BigAutoField`; `USE_TZ=True`
  (TIME_ZONE env, default UTC); persistent connections (`CONN_MAX_AGE=60`,
  health checks); dev uses discrete `DB_*` vars, prod `DATABASE_URL` +
  `sslmode=require`.
- Existing schema style: verbose `help_text`, `db_index=True` on hot columns,
  `Meta.indexes` for composite indexes (see `notification.SmsMessage`),
  audit columns as `created_by/modified_by` FKs to `auth.User` +
  `created_at/updated_at`, and dedicated append-only audit tables
  (`account.AccountAuditLog` records action, old/new values, user, client IP).
- **Cache is LocMemCache — per-process, not shared.** Deployment is
  single-Gunicorn-worker; anything cross-process (locks, schedules) must live
  in Postgres, not the cache. Precedent: `environmental_monitoring.PollLock`
  (row lock via `select_for_update` + stale-lock takeover).

## 7. Existing Integration & Background-Job Patterns (the two blueprints)

### 7a. Provider pattern — `notification` app (SMS)

- `providers/base.py`: ABC `SmsProvider` with a stable `name`, one abstract
  method; **providers never retry internally** — `retry.py`/service layer owns
  retry policy; transient vs permanent failures are distinct exception types
  (`exceptions.py`).
- `providers/mock.py` + `providers/smsgatewayhub.py`; provider selected by
  config key (`SMS_PROVIDER`).
- `dtos.py` for provider-agnostic result objects; `conf.py` is the only place
  reading Django settings.
- Runtime config = **DB-backed singleton with env fallback**
  (`SmsSettings.get_solo()`, pk forced to 1) editable from an ERP settings
  page; secrets currently stored **plaintext** (see Decisions).
- Permanent append-only log (`SmsMessage`) with sanitized request context,
  gateway response JSON, retry chain (`retry_of`/`retry_count`), status enum.

### 7b. Background sync — `environmental_monitoring` app

- Management commands (`poll_sensors`, `evaluate_alerts`) scheduled
  **externally** (Windows Task Scheduler in dev, cron/systemd timer in prod) —
  deliberately *not* an in-process scheduler, because LocMemCache is
  process-local. Overlap protection via Postgres `PollLock`.
- Async/external SDK quarantined behind a synchronous client class; DTOs cross
  the boundary; services (`hub_service`, `sensor_service`, `alert_service`)
  do the DB work; per-hub failures are caught and logged without aborting the
  run. Alerting precedent: threshold defaults master + alert list page.

**Implication:** the TrackoLap sync must be a management command
(`sync_tracking`) with a Postgres lock row, invoked by the OS scheduler, going
through `TrackingProvider` ABC → `TrackoLapProvider` (the only module that
knows TrackoLap's endpoints), with incremental sync cursors, retry
classification, and an append-only sync/error log table. UI never calls
TrackoLap; it reads ERP tables only. This matches the required
"AI-ready / no direct TrackoLap queries" constraint automatically.

## 8. Existing REST API Conventions

From `account/api_views.py` (the most recent, most polished pattern):

- Module docstring listing every route; plain `View` subclasses; all
  endpoints `login_required`; JSON body parsed manually; paginated list
  endpoints with `MAX_PAGE_SIZE` clamp; write endpoints record an audit row
  with acting user + client IP (`_client_ip` reads `X-Forwarded-For`).
- URL names prefixed `api_*`, attached to their owning tab in
  `user/access.py` `extra_urls` so the permission matrix guards them.

## 9. CRM (Customer Master)

`sales.Customer` (+ `CustomerGroup`, `CustomerShippingAddress`): name, phones,
GSTIN, contact_type (Supplier/Customer/Both), credit fields. **No geo
coordinates today.** Customer visit records will FK to `sales.Customer`;
visit history embeds into the existing Customer Master detail UI; customer
geocoding (for visit-location matching and geofences) is new data the
tracking module owns rather than a schema change on `sales.Customer`.

## 10. Notifications

SMS infrastructure is complete (templates catalog, settings, history).
There is **no in-app web notification framework**; environmental_monitoring's
Alert model + alert list page is the precedent for tracking alerts
(offline, geofence exit, late check-in, missed visit) with optional SMS
fan-out through the existing `sms_service` later.

## 11. Logging, Errors, Testing, Deployment

- Rotating file logs (`logs/info.log`, `logs/error.log`) + console; loggers
  named per app (`logging.getLogger("environmental_monitoring.poll")` style).
- Tests: per-app `tests.py` (account has a substantial suite), plus root
  `tests/`. Django `TestCase` style.
- Deployment: Gunicorn (+ WhiteNoise), Nginx on droplet or DO App Platform;
  Procfile present. Anything long-running must be a management command, not a
  daemon thread in the web process.

---

## 12. Gap Analysis (what does not exist yet)

| Needed for tracking | Exists today? |
|---|---|
| Provider abstraction for GPS vendors | No — but SMS provider pattern is a direct template |
| Background sync scheduler | No — but poll_sensors command + PollLock is a direct template |
| GPS/location tables | None anywhere |
| Credential encryption | **None** — no `cryptography` dependency, SMS key stored plaintext |
| Map rendering (Leaflet/Google) | None |
| Branch/Department org entities | None in HR — Warehouse / hr.Group / Designation are the filter axes |
| GPS fields on Attendance | None — must extend, not modify |
| Customer geo-coordinates | None on `sales.Customer` |
| In-app alert/notification UI | Only env-monitoring's Alert list precedent |

## 13. Decisions Requiring Approval Before Phase 2

1. **New app `tracking`** at project root (models, services, providers,
   management commands, templates, urls), section(s) added under the HR nav
   in `user/access.py`. *(Recommended — matches every existing convention.)*
2. **Credential encryption**: add the `cryptography` package (Fernet). Key
   from a dedicated `TRACKING_ENCRYPTION_KEY` env var (fallback: derived from
   `SECRET_KEY`). This is the **only new Python dependency** for Phases 2–4.
3. **Scheduler**: OS-level scheduling of `python manage.py sync_tracking`
   (cron/systemd timer/Task Scheduler) with a Postgres sync-lock, exactly like
   `poll_sensors`. Celery/Redis deliberately **not** introduced.
4. **Maps**: Leaflet + OpenStreetMap as the default (no API key, CDN-loaded
   like the rest of the stack) with a pluggable tile/provider setting so
   Google Maps can be enabled by configuration. Marker clustering via
   Leaflet.markercluster.
5. **API style**: plain Django `View` + `JsonResponse` + `login_required` +
   Web-Access `extra_urls` registration (account pattern). DRF stays unused.
6. **"Branch / Department" dashboard filters** map to existing entities:
   Branch → `inventory.Warehouse`, Department → `hr.Group`, plus
   `Designation` for the Salesman filter. No new org models.
7. **Location-history scale**: `employee_location_history` designed
   partition-ready (monthly range partitions on the GPS timestamp, created via
   raw-SQL migration; BRIN index on timestamp, composite B-tree on
   `(employee_id, recorded_at)`), summaries pre-aggregated into
   `employee_route` / travel-summary rows so dashboards never scan raw pings.
8. **TrackoLap API details** (base URL, auth flow, endpoint list, rate limits,
   webhook capability) are needed from you at Phase 3 — no credentials will
   ever be hardcoded; they live encrypted in `employee_tracking_provider`.

## 14. Planned Phase Map (unchanged from the brief)

Phase 2 Database → Phase 3 Provider layer (TrackoLap) → Phase 4 Background
sync → Phase 5 Live dashboard → Phase 6 Attendance integration → Phase 7
Customer visits → Phase 8 Reports → Phase 9 Testing. Each phase ends with a
report: what was built, files touched, decisions, and a no-regression check.
