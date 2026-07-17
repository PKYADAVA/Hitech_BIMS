# Employee Tracking Module

Provider-agnostic GPS employee tracking for BIMS, integrating TrackWick
(formerly TrackoLap) with a pluggable provider layer. Lives in the `tracking`
app; screens sit under **HR → Employee Tracking**.

Phase-1 analysis and architecture decisions: `EMPLOYEE_TRACKING_ANALYSIS.md`.

---

## Architecture

```
TrackWick / future vendors
        │  (HTTPS pull; optional webhook ping)
        ▼
tracking/providers/           adapter per vendor (only code that knows a wire format)
        ▼  DTOs (tracking/dtos.py)
tracking/services/sync_service.py   incremental windows · retry · dedup writers
        ├── route_service.py        daily route summaries (distance/idle/polyline)
        ├── attendance_service.py   GPS attendance → approval → hr.Attendance
        └── report_service.py       report builders (aggregated tables only)
        ▼
PostgreSQL employee_* tables  ──►  pages + JSON APIs (tracking/api_views.py)
```

Rules the module never breaks:

* The browser **never** calls a GPS vendor; everything goes vendor → DB → UI.
* `hr.Attendance` is written only by `attendance_service.mirror_to_hr`
  (manual entries and leave statuses are never overwritten — payroll safe).
* Credentials are Fernet-encrypted at rest (`tracking/crypto.py`) and
  write-only in every API/admin form.
* Dashboards and reports read pre-aggregated tables, never raw pings.

## Setup / commissioning checklist

1. **Encryption key** (`.env`) — required in production:
   `TRACKING_ENCRYPTION_KEY=<Fernet key>`
   Generate: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   (Without it a SECRET_KEY-derived key is used; rotating SECRET_KEY then
   invalidates stored credentials.)
2. **Migrate**: `python manage.py migrate tracking`
3. **Permissions**: grant the tracking tabs (Live Dashboard, Attendance Map,
   Customer Visits, Route History, Reports, Geofences, Alerts, Settings) to
   the relevant groups in User → Web-Access.
4. **Configure** at HR → Employee Tracking → **Tracking Settings**:
   * General: enable the module, thresholds (offline/idle minutes, late
     check-in / early exit times), attendance approval mode.
   * Providers → Add Provider: API base URL **`https://app.trackolap.com`**
     (bare host — endpoint paths carry their own `cust/1/api/...` /
     `integration/api/...` prefixes), plus the Customer ID (`tlp-cid`) and
     API key from TrackWick → Manager → Account Setting → API Config. Then
     **Test Connection**.
   * Confirmed against the account's official API document: employees/live
     both read `cust/1/api/asset/list` (paginated; each record embeds
     latitude/longitude/lastGPS/lastHeartbeat, so no separate live endpoint
     is needed), history reads `cust/1/api/asset/history` (params
     `start_time`/`end_time` epoch ms + the **raw asset id**, capped at
     <24h per request — the adapter resolves the raw id from the empId code
     and chunks longer windows automatically).
   * **Visits and attendance are not auto-synced.** The document defines no
     bulk, dated fetch for either: `cust/1/api/task/list` needs a
     separately licensed module; `cust/1/api/punch/in/out` *records* a punch
     (pushes into TrackoLap, e.g. from a biometric device) rather than
     listing history, and `integration/api/get?type=punchin/punchout` only
     answers "is this one employee punched in right now" with no
     timestamp/coordinates/date range. No vendor geofence endpoint exists —
     geofences are managed locally in the ERP.
   * Any path/param can still be overridden per provider via the *Endpoint
     Overrides* JSON (defaults: `tracking/providers/trackwick.py::DEFAULT_ENDPOINTS`).
     An empty path disables a kind — how visits/attendance/geofences are
     switched off today, and how a future real endpoint would be enabled.
   * Employee Mapping: load the vendor directory and map any identities the
     phone/name auto-match could not resolve. If HR has no employee records
     for these people yet (a fresh deployment, or a different vendor-tracked
     workforce than HR currently holds), preview and create them first:
     ```
     python manage.py seed_employees_from_provider          # preview, creates nothing
     python manage.py seed_employees_from_provider --apply  # commit
     ```
     Safe to re-run — it skips anyone already matching an existing employee
     by name. Run this per-database (local, staging, production each have
     their own HR data) via that environment's shell/Console.
5. **Schedule the sync** (OS scheduler — cron/systemd timer/Windows Task
   Scheduler; there is deliberately no in-process scheduler). On this
   Windows dev box, two tasks are already registered (Task Scheduler →
   Task Scheduler Library):
   * **BIMS Tracking Live Sync** — every 2 min, `sync_tracking --kinds live`
   * **BIMS Tracking Full Sync** — every 15 min, `sync_tracking` (all kinds)

   Both run as the logged-in user against `.venv\Scripts\python.exe manage.py`
   with working directory `F:\Hitech_BIMS`. Manage them from Task Scheduler
   (disable/delete/change interval) or via PowerShell:
   ```
   Get-ScheduledTask -TaskName "BIMS Tracking*" | Get-ScheduledTaskInfo
   Disable-ScheduledTask -TaskName "BIMS Tracking Live Sync"
   ```
   Equivalent cron/systemd-timer form for a Linux deployment:
   ```
   */2 * * * *   python manage.py sync_tracking --kinds live
   */15 * * * *  python manage.py sync_tracking
   ```
   First-run backfill: `python manage.py sync_tracking --lookback-hours 72`.
   Overlapping runs are prevented by a Postgres lock (stale after 10 min).
6. **Webhook (optional)**: register
   `https://<host>/api/tracking/webhook/<provider_id>/` with the vendor and
   set the same value in the provider's *Webhook Secret*. Requests must send
   the secret in the `X-Webhook-Secret` header; a valid receipt triggers an
   immediate live sync for that provider.

## TrackWick specifics

Every request carries: `platform: API`, `tlp-cid: <customer id>`,
`tlp-t: <epoch ms>`, `api-key: <key>`. Timestamps are exchanged as epoch
milliseconds. The adapter tolerates common field aliases (`lat`/`latitude`,
epoch-ms/ISO datetimes) and several response envelopes.

## Operations

* **Sync health**: Tracking Settings shows per-provider last status/error;
  every run is a row in `employee_tracking_sync`; failures also land in
  `employee_tracking_logs` (`log_type=sync`).
* **Alerts** (offline, GPS disabled, geofence entry/exit, late check-in,
  early exit): HR → Employee Tracking → Alerts. Alerts fire on state
  *transitions* only, so sync replays never duplicate them.
* **Audit**: settings/provider/mapping/geofence changes and approval
  decisions are logged with acting user + IP (`log_type=audit`).
* **Scale**: `employee_location_history` is the only unbounded table —
  BRIN + composite indexes, no inbound FKs, ready for monthly partitioning
  (pg_partman) without schema changes. `history_retention_days` in settings
  records the intended archival horizon.
* **Tests**: `python manage.py test tracking --noinput` (118 tests).

## Extending

* **New GPS vendor**: implement `TrackingProviderAdapter`
  (`tracking/providers/base.py`), register it in
  `tracking/providers/__init__.py::ADAPTERS`, add the type to
  `TrackingProvider.PROVIDER_CHOICES`. Nothing else changes.
* **New report**: one builder function + one entry in
  `tracking/services/report_service.py::REPORTS`.
* **New screen**: add the tab in `user/access.py` under the HR module and a
  link in `templates/_subnav.html` / `main_top_navbar.html`.

## AI-ready

Questions like "Where is Rahul?", "Who checked in late today?", "Which
salesman travelled the longest?", "Who missed customer visits?" are all
answerable from the ERP's own tables/APIs without touching the vendor:
`employee_live_location`, `employee_attendance_gps` (`is_late`),
`employee_route` (`total_distance_km`), `employee_customer_visit` +
`employee_tracking_logs`, and the report endpoints
(`/api/tracking/reports/?report=…`).
