# Alerts & Notifications (`alerthub`)

Business-event alerting for the ERP: *"mortality on BR-26031 crossed 1.28%"*,
*"Akbarpur has two days of feed left"*, *"this supplier bill has been entered
twice"*.

## Not to be confused with `alerts`

This project has two apps whose names both mean "alert", and telling them apart
is the first thing to know:

| | `alerts` | `alerthub` (this app) |
|---|---|---|
| Records | what a **user did to a row** — create / update / delete | what the **business needs someone to look at** |
| Triggered by | Django signals on every model | a scheduled scan reading transaction data |
| Graded by | technical severity (info → critical) | operational priority (Critical / High / Medium / Low) |
| Surface | `/alerts/center/`, staff audit trail | the navbar bell, `/notifications/`, the dashboard widget |

The navbar bell shows **this** app. The audit trail keeps its own page.

`alerthub` is in `ALERT_SETTINGS["IGNORE_APP_LABELS"]` and must stay there.
Without it, every notification written here is a row create, which the audit app
turns into an audit alert, which is itself a row create — the feedback loop that
had to be unwound in commit `9afdc1b`.

---

## How an alert happens

```
run_alert_scan (scheduled)
      │
      ▼
services.scan()  ── walks active AlertRule rows, isolating each one
      │
      ▼
detectors/<module>.py  ── queries the business data, finds breaches
      │
      ▼
engine.raise_alert()
      ├─ cooldown: has this exact subject alerted recently? → drop
      ├─ audience: scoping.audience_for() → groups ∩ data scope ∩ preferences
      ├─ no audience → nothing is written at all
      └─ write Notification + one NotificationRecipient per user
                     │
                     ▼
      the bell / centre / widget read it back through
      scoping.visible_notifications()
```

### Why a scan and not signals

Most of these conditions are not events. "A flock reached harvest age" and "an
invoice went overdue" happen because a date passed, with no row being saved.
A query-based scan also cannot trigger itself, which is the property the audit
feed lost.

---

## Security: two gates, both applied on every read

A user sees a notification only if **both** hold:

1. **Targeting** — a `NotificationRecipient` row joins them to it.
2. **Scope** — every scope column on the notification (branch / org centre /
   farm / warehouse) is inside their *current* access.

The second is not redundant. Targeting is decided once, when the alert is
raised; access changes afterwards. Someone moved off a branch keeps their
recipient rows, and without the re-check would keep reading that branch's
alerts. There is a test for exactly this
(`test_losing_access_hides_already_delivered_alerts`).

Scope delegates to `user.services.scoping`, so this module can never drift from
the Web-Access matrix. Note:

* **Cost Centre is not a separate dimension.** `account.OrganizationCentre` with
  `category=COST` *is* the cost centre.
* `GroupAccessProfile` has no org-centre scope, so it is derived from the branch
  scope through `OrganizationCentre.branch` (see `scoping._org_centre_limit`).
* **Empty scope columns are visible.** A system alert has no branch; that means
  "not about a branch", not "about a branch you lack".

---

## The catalogue

`catalog.py` holds one `RuleSpec` per alert in the specification — **all 69**,
including those nothing can raise yet.

* `requires == ""` → a detector exists and it will fire. **40 of 69.**
* `requires` set → names the data that does not exist yet (a reorder level on
  the item master, a vaccination schedule, a backup monitor). Configurable and
  visible, marked in the UI, refused by the scanner.

That completeness is deliberate: a rule that looks armed and never fires is
worse than one that admits what it is waiting on, because the first teaches
people to distrust the whole feed. `/alert-catalog/` renders this map.

Adding a detector later is a two-line change — clear `requires`, register the
function. `test_catalog.py` fails if the catalogue promises something no
detector implements, or vice versa.

---

## Commands

```bash
# One starter rule per supported alert, at the catalogue's own defaults.
# Created DISABLED — seventy watches switched on against live data would bury
# the feed on the first scan. Idempotent.
python manage.py seed_alert_rules
python manage.py seed_alert_rules --activate --group "Farm Supervisors"

# Evaluate the active rules. Schedule this every 15 minutes; the per-rule
# cooldown stops a frequent scan from repeating itself.
python manage.py run_alert_scan
python manage.py run_alert_scan --rule-key production.high_mortality
python manage.py run_alert_scan --dry-run     # what would run, not what would fire

## What actually runs the scan

Nothing did, for a long time: the README said "run it on a schedule" and no
schedule was ever created, so every part of the chain worked and the chain was
never started. Two things fixed that, and both need setting up once.

**The clock** is `.github/workflows/alert-scan.yml` — a scheduled GitHub
Actions run every 15 minutes that POSTs to `/tasks/alert-scan/`. It is not a
cron on the server because App Platform has no cron of its own (its jobs run on
deploy, not on a clock), and not a worker component because one would exist
only to sleep between fifteen-second bursts of work. Actions minutes are free
on a public repository.

**The door** is `alerthub/trigger.py`. The URL is in a public repository, so
the token is the only thing protecting it: no `ALERT_SCAN_TOKEN` in the
environment and the endpoint 404s, a wrong token gets the same 404 a wrong URL
gets, the comparison is constant-time, and a GET never scans.

Setup, once:

1. Pick a long random token.
2. App Platform → Settings → App-Level Environment Variables → `ALERT_SCAN_TOKEN`, Encrypted.
3. GitHub → Settings → Secrets and variables → Actions → `ALERT_SCAN_TOKEN`, the same value.
4. Run the workflow by hand once (Actions → Alert scan → Run workflow) and watch what it raises.

### Before switching it on

A rule with no `notify_groups` goes to **every active user** — the fail-open
that lets rules be configured before anyone has decided who should hear from
them. Harmless while nothing runs the scan, loud the moment something does:

```
python manage.py set_alert_audience --group "Managers" --dry-run
python manage.py set_alert_audience --group "Managers"
```

It only fills in rules that name nobody; a rule someone has already aimed at a
group is left alone unless you pass `--replace`.

```

There is no lock: overlapping runs both do the work (duplicates are still
suppressed by the cooldown), so keep the interval longer than a scan takes.

---

## URLs

| Path | What |
|---|---|
| `/notifications/` | Notification Centre — filters, priority strip, grouping |
| `/notifications/history/` | Dense table: who was told, when, did they read it |
| `/notifications/<id>/` | Detail — full message, measurement, related record, recipients |
| `/notifications/preferences/` | Per-user channels, sound, desktop, minimum priority |
| `/alert-config/` | Alert Configuration master |
| `/alert-catalog/` | Every alert type and whether it is ready |
| `/api/alerthub/notifications/` | Feed. `+ unread_count/ recent/ summary/ mark_all_read/` |
| `/api/alerthub/preferences/` | The caller's own preferences |

The API prefix is `/api/alerthub/` rather than `/api/notifications/` because the
`notification` app (SMS) already owns that word.

Permission-wise: the config master and catalogue are matrix-gated tabs
(`alert_rule_list`, `alert_catalog`). The centre, history, detail, preferences
and the API are in `PUBLIC_URL_NAMES` — every user reads the alerts addressed
to them regardless of which modules they can open, and the payload is scoped per
user anyway.

---

## Channels

Only **in-app** has a transport. Email / SMS / WhatsApp are stored on the rule
and on user preferences so the intent survives until a provider is connected;
`engine._deliver` refuses anything outside `LIVE_CHANNELS` and records what
actually went out. A notification history must never claim an SMS was sent when
no gateway was called.

Delivery is near-real-time by polling (30s badge refresh), matching the existing
bell. Django Channels is not a dependency; `alerts/consumers.py` is there if
WebSockets are ever wanted.

---

## Front end

`static/css/alerthub.css` and `static/js/alerthub.js`, loaded by `base.html` and
shared by the bell, the centre, the history table and the dashboard widget. One
implementation of "fetch alerts and draw them" — a card that renders differently
in two places is how a priority colour ends up meaning two things.

The four priority tokens in `:root` are the only place red/orange/blue/green are
decided.

> **WhiteNoise serves `staticfiles/`, not `static/`.** Edits to either file are
> invisible until `python manage.py collectstatic` runs. Bump the `?v=` in
> `base.html` at the same time.

---

## Tests

```bash
python manage.py test alerthub
```

50 tests. The ones that matter most:

* `test_scoping.py` — the security boundary. Cross-branch leakage, revocation
  taking effect on read, targeting vs. scope, priority ranking not being
  alphabetical.
* `test_detectors.py` — every one of the 40 detectors *executes* against an
  empty database. They reference fields across other apps and only run from a
  scheduled command, so a rename elsewhere would otherwise break them silently:
  the scan catches the exception, logs it, and the alert just never arrives.
* `test_catalog.py` — the catalogue's "Ready" badge cannot become a lie.
* `test_engine.py` — dedupe windows, delivery honesty, failure isolation.
