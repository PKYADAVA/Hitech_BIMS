# Deployment Guide — Hitech BIMS

Primary deployment target: **DigitalOcean App Platform**, backed by a
**DigitalOcean Dev PostgreSQL Database**, with GitHub → App Platform auto-deploy
on every push to `main`.

```
GitHub Repository --> App Platform Auto Deploy --> Build (buildpack) --> Run (migrate + Gunicorn)
                                                                              |
                                                                        DigitalOcean Dev PostgreSQL
```

An alternative path (self-managed Ubuntu Droplet + Nginx + systemd) also
exists in this repo and is documented separately in [§B](#part-b-alternative-self-managed-droplet-deployment) —
skip to there only if you're not using App Platform.

---

# Part A — DigitalOcean App Platform (primary path)

## A1. How this app is built and run

App Platform detects this is a Python app via buildpack (no Dockerfile
needed) and uses:

- **`runtime.txt`** / **`.python-version`** — pins the Python version to
  `3.11.9`. Without this, the buildpack defaults to whatever its newest
  supported Python is, which has been observed to break Django 4.2 (see
  Troubleshooting below).
- **`requirements.txt`** — dependencies.
- **`Procfile`** — the run command:
  ```
  web: python manage.py migrate --noinput && (python manage.py seed_sms_templates || true) && gunicorn --config gunicorn.conf.py --bind 0.0.0.0:$PORT Hitech_BIMS.wsgi:application
  ```
  `seed_sms_templates` is idempotent — it creates any SMS templates missing
  from the database and leaves existing (possibly admin-edited) ones untouched,
  so new templates ship automatically on deploy. It's wrapped in
  `(... || true)` so a seeding hiccup can never block Gunicorn from starting;
  `migrate` still gates startup as before.

### Build Command

Set explicitly in the App Platform dashboard (**Settings → your component →
Build Command**), or leave it on the buildpack default, which does the
equivalent of:

```bash
pip install -r requirements.txt && python manage.py collectstatic --noinput
```

Nothing else should run at build time — no `migrate` here. The database
often isn't reachable (or the schema isn't ready) at build time, and
`collectstatic` doesn't need it; keeping the build command minimal also
keeps build times down.

### Run Command

Either rely on the `Procfile` above, or set the same thing explicitly as the
**Run Command** in the dashboard (a dashboard-configured Run Command
overrides the `Procfile` if both are present — don't set both to different
things):

```bash
python manage.py migrate --noinput && (python manage.py seed_sms_templates || true) && gunicorn --config gunicorn.conf.py --bind 0.0.0.0:$PORT Hitech_BIMS.wsgi:application
```

Running `migrate` as part of the run command (rather than a separate step)
means: every instance restart re-checks migration state (cheap/no-op if
already applied), and — importantly — if migrations fail, Gunicorn never
starts, so the app shows as failed/crashed in the dashboard instead of
silently serving 500s against a broken schema. This is deliberate.

**Caveat:** if you ever scale this component to more than 1 instance,
multiple instances will run `migrate --noinput` concurrently on deploy. Django
skips already-applied migrations, so this is normally safe, but a first-ever
migration run under concurrent instances could race. At 1 instance (the
default/Dev tier), this doesn't apply. If you scale up, consider moving
`migrate` to a dedicated "Pre-Deploy Job" component instead (App Platform
runs those once, before any web instance starts).

## A2. Environment Variables

App Platform env vars are set in the dashboard: **App → Settings →
Environment Variables** (app-level, or per-component). See `.env.example` in
this repo for the full list with comments. The ones that matter most:

| Variable | Value | Notes |
|---|---|---|
| `SECRET_KEY` | a generated secret | **Type: Encrypted.** Must be marked **"Available at Build Time"**, not just Run Time — `collectstatic` needs it during the build. |
| `DEBUG` | `False` | |
| `DEVELOPMENT_MODE` | `False` | Switches `DATABASES` to parse `DATABASE_URL` instead of individual `DB_*` vars. |
| `ALLOWED_HOSTS` | your `*.ondigitalocean.app` domain (and custom domain if any) | Required the moment `DEBUG=False`. |
| `DATABASE_URL` | from your DO database | If the database is attached as a bound component, App Platform can auto-inject this (`${db.DATABASE_URL}` in the app spec) instead of you pasting it manually. |
| `CSRF_TRUSTED_ORIGINS` | `https://your-app.ondigitalocean.app` | |
| `DB_SSLMODE` | `require` | Default already assumed by `settings.py` if unset; DO's managed databases reject non-SSL connections. |

Generate `SECRET_KEY` with:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

**Never commit real secret values to git** — not to `.env` (gitignored), and
not into an app spec YAML either. Set them through the dashboard/secrets
mechanism only.

## A3. Database — DigitalOcean Dev PostgreSQL

1. Create (or use an existing) **Dev Database** cluster from the DigitalOcean
   dashboard, or attach one directly from the App Platform app creation flow.
2. Get the connection string from the database's **Connection Details**
   panel and set it as `DATABASE_URL` (see A2). It already includes
   `?sslmode=require`.
3. **Grant schema privileges to the app's DB user.** On Postgres 15+,
   non-owner users no longer get `CREATE` on the `public` schema by default —
   this **will** cause the first `migrate` to fail (see Troubleshooting).
   Connect as the cluster's admin user (`doadmin`) and run:
   ```sql
   GRANT ALL ON SCHEMA public TO your_app_db_user;
   ```
   Do this against the **same database name** that appears in `DATABASE_URL`
   — a grant on the wrong database (e.g. `defaultdb` when the app actually
   uses a different one) won't help.
4. Redeploy (or manually re-run `python manage.py migrate --noinput` from
   the App Platform **Console** tab) once the grant is in place.

`settings.py`'s `DATABASES` configuration for this path (`DEVELOPMENT_MODE=False`):
- Parses `DATABASE_URL` via `dj_database_url`.
- `CONN_MAX_AGE` (default 60s, env `DB_CONN_MAX_AGE`) — persistent
  connections instead of reconnecting every request.
- `CONN_HEALTH_CHECKS = True` — verifies a pooled connection is still alive
  before reuse.
- `connect_timeout` (default 10s, env `DB_CONNECT_TIMEOUT`).
- `sslmode` defaults to `require` (env `DB_SSLMODE`) unless `DATABASE_URL`
  already specifies one.

True connection pooling (pgbouncer-style) isn't configured — Dev Database
tiers have a low connection cap (commonly ~22), and at App Platform Dev
tier's typical single-instance / few-Gunicorn-worker scale, Django's
`CONN_MAX_AGE` persistent connections stay well under that without adding
another moving part. Revisit if you scale up meaningfully.

## A4. Static Files — WhiteNoise

No Nginx exists in front of the app on App Platform, so Django/Gunicorn must
serve static files itself:

- `whitenoise.middleware.WhiteNoiseMiddleware` sits directly after
  `SecurityMiddleware` in `MIDDLEWARE`.
- `STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"` —
  gzip-compresses static files at `collectstatic` time.
  - **Not** `CompressedManifestStaticFilesStorage` (the hashed/cache-busting
    variant): verified directly that `staticfiles_storage.url()` keeps
    returning un-hashed paths even though the hash manifest itself is
    generated correctly, so that variant provides no actual cache-busting
    benefit here — reverted after testing rather than shipped half-working.
- `collectstatic` runs at build time (see A1) into `STATIC_ROOT`
  (`staticfiles/`), which is `.gitignore`d — it's a build artifact,
  regenerated on every build, not versioned.

Because there's no hashed filenames, static assets get `Cache-Control:
max-age=0, public` rather than a long-lived cache — acceptable at this
app's scale; revisit if static asset traffic becomes significant.

`MEDIA_ROOT` (user-uploaded farmer/farm files) is **not** served by
WhiteNoise (it only serves `STATIC_ROOT`) and, more importantly, App
Platform's filesystem is ephemeral — uploaded media will not survive a
redeploy or restart. If this app needs durable media storage on App
Platform, that requires object storage (DigitalOcean Spaces + a Django
storage backend like `django-storages`) — not implemented in this pass since
it's a new dependency/behavior change beyond the scope of a deployment
hardening pass. Flagging it here since it'll bite the first time someone
uploads a farmer photo and it vanishes after the next deploy.

## A5. Gunicorn

`gunicorn.conf.py` at the project root, auto-loaded by Gunicorn from the
working directory (no `--config` flag strictly required, though the
`Procfile` passes it explicitly for clarity):

- `workers` — `min(3, cpu_count * 2 + 1)` by default, override with
  `WEB_CONCURRENCY`. On App Platform's smaller Dev-tier instances, consider
  setting `WEB_CONCURRENCY=1` or `2` explicitly.
- `timeout` — 120s (not Gunicorn's 30s default): several forms in this app
  accept multiple file uploads (farm pictures, agreement/cheque documents)
  and can legitimately take a while.
- `worker_tmp_dir` — uses `/dev/shm` (in-memory) when available, which it is
  on App Platform's Linux containers; avoids workers being killed as
  falsely unresponsive if the container's regular temp filesystem is slow.
- `accesslog`/`errorlog` default to `-` (stdout/stderr) so App Platform's
  own log capture picks them up — no `/var/log/...` path is assumed to
  exist or be writable.
- `preload_app = True` — faster worker startup, lower memory via
  copy-on-write.

## A6. Logging

Django's own `LOGGING` (in `settings.py`) writes to `logs/info.log` and
`logs/error.log` (rotating, 1MB × 10 backups) **and** to console
(`WARNING`+ in production, `INFO`+ when `DEBUG=True`) simultaneously. On App
Platform, the container filesystem is ephemeral, so the file handlers are
mostly redundant there — the **console output is what actually matters** on
this platform, since that's what App Platform's **Runtime Logs** tab
captures. Use that tab (or `doctl apps logs`) rather than expecting to find
persisted log files on the instance.

## A7. Health Checks

App Platform performs HTTP health checks against the component automatically.
By default it checks the root path. If that ever needs to be something
lighter-weight than the full home page (e.g. once the app has expensive
dashboard queries on `/`), point the App Platform **Health Check Path**
setting at a cheap endpoint instead — not currently needed at this app's
scale, noting it here for when it becomes relevant.

## A7b. Scheduled Jobs — Employee Tracking Sync

The Employee Tracking module (`tracking` app) pulls GPS data from the
configured provider via `python manage.py sync_tracking` (see
`EMPLOYEE_TRACKING.md`). This **must run on a schedule against the
production database** — it does not run itself, and a schedule set up on a
developer's local machine (e.g. Windows Task Scheduler) only syncs that
machine's local database, never production. On App Platform, the schedule
lives in the app itself as one or two **Scheduled Job** components (App →
**Create/Edit Component → Job**, trigger type **Scheduled**), which share
this app's repo, build, and environment variables automatically:

| Job name | Run Command | Suggested schedule |
|---|---|---|
| `tracking-live-sync` | `python manage.py sync_tracking --kinds live` | every 5 min (or the shortest interval the Scheduled Job UI offers) |
| `tracking-full-sync` | `python manage.py sync_tracking` | every 15–30 min |

Notes:
- Jobs run in the same container image as the web component — no separate
  build/deploy config needed, just the Run Command and cron schedule.
- The sync is lock-guarded (`SyncLock`, in Postgres) so overlapping runs
  between the two jobs — or a slow run bumping into the next tick — can't
  corrupt data; the second run simply skips with "already in progress".
- **First-time backfill**: once the jobs exist, also run once, manually,
  from the App Platform **Console** tab (or trigger a one-off Job run):
  ```
  python manage.py sync_tracking --trigger manual --lookback-hours 48
  ```
  Without this, the dashboard stays empty until the first scheduled tick
  naturally catches up (which it will, just later).
- **Provider credentials and the Employee↔vendor mapping are per-database.**
  Entering a provider or mapping employees locally has no effect on
  production — repeat that setup in production's own Tracking Settings page
  the first time (Test Connection there only proves TrackoLap reachability,
  not that any data has synced).

## A8. Deployment Flow

1. Push to `main` (or merge a PR into it).
2. App Platform's GitHub integration detects the push and starts a build
   automatically (no separate CI step required for this path — unlike the
   Droplet path's GitHub Actions workflow).
3. Build phase: install deps, `collectstatic`.
4. Run phase: `migrate --noinput`, then Gunicorn starts.
5. App Platform health-checks the new instance before routing traffic to it
   (zero-downtime swap) and terminates the old one.

To force a rebuild without a new commit: dashboard → app → **Actions →
Force Rebuild and Deploy**.

## A9. Rollback

App Platform keeps a **Deployments** history per app (dashboard → app →
**Activity**/**Deployments** tab). To roll back:

1. Find the last known-good deployment in that list.
2. Use **Rollback** if the dashboard offers it for that deployment, or
   redeploy the corresponding git commit (`git revert`/`git reset` on
   `main` and push, or force-rebuild a specific commit if the dashboard
   supports pinning one).
3. If the bad deploy included a migration that needs reverting too, that's
   not automatic — connect via the **Console** tab and run
   `python manage.py migrate <app_label> <previous_migration_number>`
   manually before rolling the code back, or the reverted code may not match
   the still-forward-migrated schema.

## A10. Troubleshooting

Everything below was hit and fixed for real during this app's actual
deployment, in the order encountered:

| Error | Cause | Fix |
|---|---|---|
| `Could not find a version that satisfies the requirement psycopg-binary==3.2.3` | That exact pinned version had no compatible wheel available anymore | Bump `psycopg`/`psycopg-binary` in `requirements.txt` to a version confirmed available (e.g. `3.2.10`+) |
| `KeyError: 'collectstatic'` during build, traceback through `python3.14/site-packages/...` | Buildpack defaulted to a Python version (3.14) far newer than Django 4.2.6 supports; something in `django.contrib.staticfiles` fails to load silently on it | Pin the Python version via **both** `runtime.txt` (`python-3.11.9`) and `.python-version` (`3.11.9`) — different buildpack versions read different ones |
| `django.core.exceptions.ImproperlyConfigured: SECRET_KEY environment variable is not set` during `collectstatic` at build time | App Platform does **not** read `.env` — env vars must be set in the dashboard, and `collectstatic` runs at *build* time, which needs env vars explicitly marked available then, not just at runtime | Dashboard → Environment Variables → add `SECRET_KEY` (Encrypted) with **"Available at Build Time"** checked. Same applies to `ALLOWED_HOSTS`, `DATABASE_URL`, etc. |
| `FileNotFoundError: [Errno 2] No such file or directory: '/var/log/gunicorn/error.log'` on startup | `gunicorn.conf.py` (written for the Droplet path) hardcoded a log directory that doesn't exist in App Platform's ephemeral container | Default `accesslog`/`errorlog` to `-` (stdout/stderr) unless `GUNICORN_LOG_DIR` is explicitly set (only set on the Droplet path's systemd unit) |
| Login page rendered but with **zero CSS/JS** (plain unstyled HTML) | `DEBUG=False` means Django never serves `/static/` itself, and there's no Nginx on App Platform to serve it instead | Add WhiteNoise (`whitenoise.middleware.WhiteNoiseMiddleware` + `STATICFILES_STORAGE`) so Gunicorn serves static files directly |
| `django.db.migrations.exceptions.MigrationSchemaMissing: Unable to create the django_migrations table (permission denied for schema public` | Postgres 15+ no longer grants `CREATE` on `public` schema to non-owner users by default; the app's DB user isn't the database owner | Connect as `doadmin` (or your cluster's admin) and run `GRANT ALL ON SCHEMA public TO your_app_db_user;` against the **exact** database in `DATABASE_URL`, then re-run `migrate` |
| Database password visible in a pasted dashboard screenshot | Human error, not a code issue, but worth stating plainly | Treat any credential that appears in a chat log, screenshot, or shared doc as compromised — rotate it immediately (dashboard → database → **Users & Databases** → **Reset Password**), then update `DATABASE_URL` |

General debugging order when a deploy fails:
1. App Platform dashboard → app → the failing deployment → **Build Logs** or
   **Runtime Logs** (build failures and runtime crashes show in different
   tabs).
2. Check the **timestamp** on the log you're looking at — App Platform does
   not auto-retry a failed build; re-reading an old failed build's log after
   you've already pushed a fix looks identical to a fresh failure. Trigger a
   new build (push or **Force Rebuild**) and confirm the timestamp moved.
3. Cross-reference the error against the table above before assuming it's
   new — several of these look alike (any `ImproperlyConfigured` at build
   time is almost always a missing "Available at Build Time" env var).

---

# Part B — Alternative: self-managed Droplet deployment

This repo also contains a complete, independent deployment path for a
self-managed Ubuntu Droplet (Nginx + Gunicorn + systemd + GitHub Actions over
SSH), for cases where App Platform isn't the target. It shares the same
Django codebase, `gunicorn.conf.py`, and `.env.example`, but uses its own
process supervision and reverse proxy instead of App Platform's.

## B1. Provision the Droplet

- Ubuntu 22.04 LTS, 2GB RAM / 1-2 vCPU.
- Point a DNS A record at the droplet's IP if you have a domain (recommended
  for TLS via Let's Encrypt). Without one, you can still deploy over the bare
  IP and skip HTTPS.

SSH in as `root` (or a sudo-capable user) for the initial setup below.

## B2. System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib libpq-dev \
    nginx \
    git build-essential curl
```

`libpq-dev` + `build-essential` are needed to build `psycopg` if a wheel
isn't available for your platform.

## B3. Create the Deployment User

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG www-data deploy
```

Give `deploy` passwordless sudo **only** for the specific commands
`deploy.sh` needs:

```bash
sudo visudo -f /etc/sudoers.d/deploy
```
```
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart gunicorn, /bin/systemctl reload nginx, /usr/sbin/nginx -t, /bin/systemctl is-active --quiet gunicorn
```

Generate an SSH keypair for GitHub Actions and authorize it for `deploy`:

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
ssh-keygen -t ed25519 -C "github-actions-deploy" -f /tmp/deploy_key -N ""
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < /tmp/deploy_key.pub
sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
cat /tmp/deploy_key   # copy into the SSH_PRIVATE_KEY GitHub secret, then delete
rm /tmp/deploy_key /tmp/deploy_key.pub
```

## B4. PostgreSQL

```bash
sudo -u postgres psql
```
```sql
CREATE DATABASE hitech_bims;
CREATE USER hitech_bims_user WITH PASSWORD 'choose-a-strong-password';
ALTER ROLE hitech_bims_user SET client_encoding TO 'utf8';
ALTER ROLE hitech_bims_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE hitech_bims TO hitech_bims_user;
\q
```

On Postgres 15+, also grant schema privileges (same underlying issue as
App Platform's Troubleshooting entry above):

```sql
\c hitech_bims
GRANT ALL ON SCHEMA public TO hitech_bims_user;
```

## B5. Clone the Project and Set Up the Virtualenv

```bash
sudo -u deploy -i
git clone git@github.com:PKYADAVA/Hitech_BIMS.git /home/deploy/hitech_bims
cd /home/deploy/hitech_bims
python3.11 -m venv hitech_env
source hitech_env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`PROJECT_PATH` below refers to this directory (e.g. `/home/deploy/hitech_bims`).

## B6. Environment Variables

```bash
cp .env.example .env
nano .env
```

Same required variables as Part A2, plus for this path specifically:
`DEVELOPMENT_MODE=True` with individual `DB_*` vars is also a valid option
(not just `DATABASE_URL`) since you control the Postgres instance directly.

`chmod 600 .env`. Never commit it — `.gitignore` already excludes it.

## B7. First-Time Django Setup

```bash
source hitech_env/bin/activate
python manage.py migrate
python manage.py seed_sms_templates
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

On the Droplet path the run command comes from `deploy/gunicorn.service`, not
the `Procfile`, so seeding isn't automatic there. Run `seed_sms_templates`
after each `migrate` (e.g. add it to your GitHub Actions deploy step, right
after the migrate command). It's idempotent, so re-running it is harmless.

## B8. Gunicorn (systemd)

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/gunicorn.service
sudo sed -i "s#%PROJECT_PATH%#/home/deploy/hitech_bims#g; s#%DEPLOY_USER%#deploy#g" /etc/systemd/system/gunicorn.service
sudo mkdir -p /var/log/gunicorn && sudo chown deploy:deploy /var/log/gunicorn
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn
sudo systemctl status gunicorn
```

This is the one place `GUNICORN_LOG_DIR` gets set (`Environment=GUNICORN_LOG_DIR=/var/log/gunicorn`
in the unit file), switching `gunicorn.conf.py` from stdout/stderr logging to
dedicated log files — appropriate here since systemd/journald plus a real
persistent filesystem back this, unlike App Platform.

## B9. Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/hitech_bims
sudo sed -i "s#%PROJECT_PATH%#/home/deploy/hitech_bims#g; s#%DOMAIN%#bims.yourcompany.com#g" /etc/nginx/sites-available/hitech_bims
sudo ln -s /etc/nginx/sites-available/hitech_bims /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

With a domain pointed at the droplet:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bims.yourcompany.com
```

Then set `SECURE_SSL_REDIRECT=True` in `.env` (already the default once
`DEBUG=False`). No domain yet? Leave `SECURE_SSL_REDIRECT=False` until TLS
is live, or every request redirects to a non-existent HTTPS listener.

## B10. Verify

```bash
curl -I http://localhost/
sudo systemctl status gunicorn nginx postgresql
sudo journalctl -u gunicorn -n 50 --no-pager
```

## B11. GitHub Actions CI/CD

Workflow: `.github/workflows/deploy.yml`. On push to `main`: runs Django
checks/tests against an ephemeral Postgres service container, then (only on
`main`, only if tests pass) SSHes into the droplet and runs `deploy.sh`.

Required GitHub Secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `DROPLET_HOST` | Droplet IP or domain |
| `DROPLET_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | The private key from B3 |
| `PROJECT_PATH` | `/home/deploy/hitech_bims` |

Ruff/Pylint steps in the workflow only run if this repo has a config for
them (`ruff.toml`/`.pylintrc`/relevant `pyproject.toml` sections) — currently
absent, so they no-op.

## B12. `deploy.sh`

Idempotent, safe to re-run. Records the current commit, `git fetch` + hard
resets to `origin/main`, installs dependencies, runs `manage.py check
--deploy`, migrates, collects static files, restarts `gunicorn`, reloads
`nginx`. **On any failure**, automatically rolls back to the previously
deployed commit, reinstalls its dependencies, and restarts Gunicorn on the
known-good version.

```bash
cd /home/deploy/hitech_bims
./deploy.sh
```

## B13. Rollback

```bash
cd /home/deploy/hitech_bims
git log --oneline -5
git reset --hard <good-sha>
source hitech_env/bin/activate
pip install -r requirements.txt
python manage.py migrate   # only if needed
sudo systemctl restart gunicorn
```

To also revert a migration: `python manage.py migrate <app_label> <previous_migration_number>`.

## B14. Backup Strategy

**Database** — daily `pg_dump`, retained 14 days:

```bash
sudo -u postgres crontab -e
```
```
0 2 * * * pg_dump -Fc hitech_bims > /var/backups/hitech_bims/db_$(date +\%Y\%m\%d).dump && find /var/backups/hitech_bims -name '*.dump' -mtime +14 -delete
```
```bash
sudo mkdir -p /var/backups/hitech_bims && sudo chown postgres:postgres /var/backups/hitech_bims
```

**Media files** — `media/` isn't in git; back it up separately, e.g. nightly:
```bash
rsync -avz /home/deploy/hitech_bims/media/ your-backup-target:/backups/hitech_bims-media/
```

Ship both off the droplet on the same schedule — a droplet-level failure
would otherwise take the backups down with it.

### Restore

```bash
pg_restore -d hitech_bims --clean --if-exists /var/backups/hitech_bims/db_YYYYMMDD.dump
rsync -avz your-backup-target:/backups/hitech_bims-media/ /home/deploy/hitech_bims/media/
sudo systemctl restart gunicorn
```

## B15. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `502 Bad Gateway` from Nginx | Gunicorn isn't running or the socket path is wrong. `sudo systemctl status gunicorn`; `ls -l /run/gunicorn/`. |
| `ImproperlyConfigured: SECRET_KEY environment variable is not set` | `.env` missing or not read — confirm `PROJECT_PATH/.env` exists and `EnvironmentFile=` in `gunicorn.service` points at it. |
| `ImproperlyConfigured: ALLOWED_HOSTS environment variable is not set` | Same as above, or `ALLOWED_HOSTS` in `.env` is empty while `DEBUG=False`. |
| `permission denied for schema public` during `migrate` | Postgres 15+ default privilege change — see A3/A10. Same fix, different admin path (`sudo -u postgres psql` here instead of a managed-DB dashboard). |
| Static files 404 | Did `collectstatic` run? Does `deploy/nginx.conf`'s `alias` path match `STATIC_ROOT` (`staticfiles/`)? |
| Cached list data looks stale across requests | Cache is per-process `LocMemCache` — restart Gunicorn workers to clear it, or reduce `CACHES.default.TIMEOUT` in `settings.py`. |
| CSRF failures on forms in production | Add the real origin to `CSRF_TRUSTED_ORIGINS` in `.env` (with scheme, e.g. `https://...`). |
| Redirect loop on every page | `SECURE_SSL_REDIRECT=True` but Nginx isn't terminating TLS yet — set `False` in `.env` until certbot has run. |
| `git reset --hard` in `deploy.sh` fails with local changes | Something was edited directly on the droplet outside git — inspect with `git status`/`git diff` before deploying again. |
| Gunicorn OOM-killed on the 2GB droplet | Lower `WEB_CONCURRENCY` in `.env`, check `dmesg \| grep -i oom`. |
| Deploy job can't SSH in | Verify `SSH_PRIVATE_KEY` matches a key in `deploy`'s `~/.ssh/authorized_keys`, and `DROPLET_HOST`/`DROPLET_USER` secrets are correct. |

```bash
sudo journalctl -u gunicorn -n 100 --no-pager
tail -100 /var/log/gunicorn/error.log
tail -100 /home/deploy/hitech_bims/logs/error.log
tail -100 /var/log/nginx/hitech_bims.error.log
```

---

# Known Gaps (Not Addressed by This Pass)

Flagged during the production readiness review but intentionally left
untouched — pre-existing application concerns, not deployment configuration,
and fixing them risks changing behavior/data outside a deployment task's
scope:

- `BroilerDisease.batch` is declared required in `models.py` but the database
  column is still nullable with existing `NULL` rows — needs a deliberate
  data decision before tightening.
- The `hatchery` app has model changes not yet captured in a migration.
- `djangorestframework` is installed but unused anywhere in the codebase.
- Media files (`MEDIA_ROOT`) have no durable storage story on App Platform's
  ephemeral filesystem (see A4) — needs object storage if pursued.
- 66+ files under `staticfiles/` were committed to git before `.gitignore`
  excluded the directory. New files won't be tracked going forward, but the
  existing ones need a one-time cleanup: `git rm -r --cached staticfiles && git commit`.
