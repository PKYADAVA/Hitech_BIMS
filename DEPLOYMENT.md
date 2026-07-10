# Deployment Guide — Hitech BIMS

Production deployment on a DigitalOcean Ubuntu Droplet (2GB), fronted by Nginx,
running Django under Gunicorn as a systemd service, backed by PostgreSQL, with
deploys automated through GitHub Actions over SSH.

```
GitHub -> GitHub Actions -> SSH -> Droplet (Nginx -> Gunicorn -> Django -> PostgreSQL)
```

---

## 1. Provision the Droplet

- Ubuntu 22.04 LTS, 2GB RAM / 1-2 vCPU.
- Point a DNS A record at the droplet's IP if you have a domain (recommended
  for TLS via Let's Encrypt). Without one, you can still deploy over the bare
  IP and skip HTTPS.

SSH in as `root` (or a sudo-capable user) for the initial setup below.

---

## 2. System Packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip \
    postgresql postgresql-contrib libpq-dev \
    nginx \
    git build-essential curl
```

- `libpq-dev` + `build-essential` are needed to build `psycopg` if a wheel
  isn't available for your platform.

---

## 3. Create the Deployment User

Run the app as an unprivileged user, not root.

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG www-data deploy
```

Give `deploy` passwordless sudo **only** for the specific commands
`deploy.sh` needs (restarting Gunicorn, reloading Nginx):

```bash
sudo visudo -f /etc/sudoers.d/deploy
```

```
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart gunicorn, /bin/systemctl reload nginx, /usr/sbin/nginx -t, /bin/systemctl is-active --quiet gunicorn
```

Generate an SSH keypair for GitHub Actions to use, and authorize it for `deploy`:

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
ssh-keygen -t ed25519 -C "github-actions-deploy" -f /tmp/deploy_key -N ""
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < /tmp/deploy_key.pub
sudo chmod 700 /home/deploy/.ssh && sudo chmod 600 /home/deploy/.ssh/authorized_keys
cat /tmp/deploy_key   # copy this private key into the SSH_PRIVATE_KEY GitHub secret, then delete /tmp/deploy_key*
rm /tmp/deploy_key /tmp/deploy_key.pub
```

---

## 4. PostgreSQL

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

On modern Postgres (15+), also grant schema privileges:

```sql
\c hitech_bims
GRANT ALL ON SCHEMA public TO hitech_bims_user;
```

Note the DB name/user/password — they go into `.env` as `DB_NAME` /
`DB_USER` / `DB_PASSWORD` (or combined into `DATABASE_URL` if you set
`DEVELOPMENT_MODE=False`).

---

## 5. Clone the Project and Set Up the Virtualenv

```bash
sudo -u deploy -i
git clone git@github.com:PKYADAVA/Hitech_BIMS.git /home/deploy/hitech_bims
cd /home/deploy/hitech_bims
python3.11 -m venv hitech_env
source hitech_env/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

`PROJECT_PATH` in every config file/secret below refers to this directory
(e.g. `/home/deploy/hitech_bims`).

---

## 6. Environment Variables

Copy the template and fill in real values:

```bash
cp .env.example .env
nano .env
```

Required for production (see `.env.example` for the full list and comments):

| Variable | Notes |
|---|---|
| `SECRET_KEY` | Generate with `python -c "import secrets; print(secrets.token_urlsafe(50))"`. Never reuse the dev key. |
| `DEBUG` | `False` |
| `DEVELOPMENT_MODE` | `False` (uses `DATABASE_URL`) or `True` (uses individual `DB_*` vars) |
| `ALLOWED_HOSTS` | Your domain and/or droplet IP, comma-separated, no `*` |
| `CSRF_TRUSTED_ORIGINS` | e.g. `https://bims.yourcompany.com` |
| `DATABASE_URL` or `DB_*` | From step 4 |
| `EMAIL_*` | SMTP credentials |

`chmod 600 .env` so only `deploy` can read it — it holds real secrets.

**Never commit `.env`.** `.gitignore` already excludes it; `.env.example`
(no real values) is the only env file tracked in git.

---

## 7. First-Time Django Setup

```bash
source hitech_env/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

---

## 8. Gunicorn

Config lives in `gunicorn.conf.py` at the project root (binds to a unix
socket at `/run/gunicorn/hitech_bims.sock`, sized for a 2GB droplet — see
comments in that file for the tunables: `WEB_CONCURRENCY`,
`GUNICORN_TIMEOUT`, etc).

Install the systemd unit:

```bash
sudo cp deploy/gunicorn.service /etc/systemd/system/gunicorn.service
sudo sed -i "s#%PROJECT_PATH%#/home/deploy/hitech_bims#g; s#%DEPLOY_USER%#deploy#g" /etc/systemd/system/gunicorn.service
sudo mkdir -p /var/log/gunicorn && sudo chown deploy:deploy /var/log/gunicorn
sudo systemctl daemon-reload
sudo systemctl enable --now gunicorn
sudo systemctl status gunicorn
```

---

## 9. Nginx

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/hitech_bims
sudo sed -i "s#%PROJECT_PATH%#/home/deploy/hitech_bims#g; s#%DOMAIN%#bims.yourcompany.com#g" /etc/nginx/sites-available/hitech_bims
sudo ln -s /etc/nginx/sites-available/hitech_bims /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

If you have a domain pointed at the droplet, get a free TLS certificate
(this rewrites the site config to add the 443 server block and HTTPS redirect):

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d bims.yourcompany.com
```

After certbot runs, set `SECURE_SSL_REDIRECT=True` in `.env` (it already
defaults to `True` once `DEBUG=False`, so this is usually a no-op — only set
it explicitly to `False` if you need to run HTTP-only for a while).

No domain yet? Skip certbot and access the app over `http://<droplet-ip>/`;
leave `SECURE_SSL_REDIRECT=False` until TLS is in place, or every request
will redirect to a non-existent HTTPS listener.

---

## 10. Verify

```bash
curl -I http://localhost/            # via Nginx -> Gunicorn -> Django
sudo systemctl status gunicorn nginx postgresql
sudo journalctl -u gunicorn -n 50 --no-pager
```

---

## 11. GitHub Actions CI/CD

Workflow: `.github/workflows/deploy.yml`. On every push to `main` it runs
Django checks/tests, then (only on `main`, only if tests pass) SSHes into the
droplet and runs `deploy.sh`.

### Required GitHub Secrets

Repo Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| `DROPLET_HOST` | Droplet IP or domain |
| `DROPLET_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | The private key generated in step 3 (`/tmp/deploy_key` contents) |
| `PROJECT_PATH` | `/home/deploy/hitech_bims` |

No other secrets are needed — the droplet's own `.env` file (not GitHub)
holds the application's runtime secrets, exactly as configured in step 6.

### What the pipeline does

1. **test job** — installs dependencies, runs Ruff/Pylint *if configured*
   (neither has a config file in this repo yet, so these steps currently
   no-op — see below), `manage.py check`, `manage.py test`, and a
   `collectstatic --dry-run` sanity check, against an ephemeral Postgres
   service container.
2. **deploy job** — only runs on a push to `main` after `test` passes. SSHes
   in as `deploy` and runs `./deploy.sh` (see below) in `PROJECT_PATH`.

To activate Ruff/Pylint in CI, add `ruff.toml` (or a `[tool.ruff]` section in
a new `pyproject.toml`) and/or `.pylintrc` to the repo — the workflow
detects them automatically.

---

## 12. `deploy.sh`

Runs on the droplet (invoked by CI, or manually). It is idempotent — safe to
re-run — and:

1. Records the currently-deployed commit.
2. `git fetch` + hard-resets to `origin/main`.
3. Installs dependencies, runs `manage.py check --deploy`, migrates, collects
   static files.
4. Restarts `gunicorn`, verifies it's active, reloads `nginx`.
5. **On any failure**, automatically `git reset --hard`s back to the
   previously-deployed commit, reinstalls its dependencies, and restarts
   Gunicorn on the known-good version.

Manual run:

```bash
cd /home/deploy/hitech_bims
./deploy.sh
```

---

## 13. Rollback

Automatic rollback (via `deploy.sh`'s trap) only covers failures *during* a
deploy. To roll back a deploy that succeeded but is misbehaving:

```bash
cd /home/deploy/hitech_bims
git log --oneline -5              # find the last-good commit SHA
git reset --hard <good-sha>
source hitech_env/bin/activate
pip install -r requirements.txt
python manage.py migrate          # only if the bad deploy didn't add migrations you need to keep
sudo systemctl restart gunicorn
```

If the bad deploy included a migration that must also be reverted:

```bash
python manage.py migrate <app_label> <previous_migration_number>
```

---

## 14. Backup Strategy

**Database** — daily `pg_dump`, retained 14 days, via cron as the `postgres`
user:

```bash
sudo -u postgres crontab -e
```

```
0 2 * * * pg_dump -Fc hitech_bims > /var/backups/hitech_bims/db_$(date +\%Y\%m\%d).dump && find /var/backups/hitech_bims -name '*.dump' -mtime +14 -delete
```

```bash
sudo mkdir -p /var/backups/hitech_bims && sudo chown postgres:postgres /var/backups/hitech_bims
```

**Media files** — `media/` holds user-uploaded farmer/farm documents and
photos and is not in git. Back it up separately, e.g. nightly `rsync` to
DigitalOcean Spaces or another host:

```bash
rsync -avz /home/deploy/hitech_bims/media/ your-backup-target:/backups/hitech_bims-media/
```

**Off-droplet copies** — don't rely solely on droplet-local backups; ship the
DB dumps and media backups off the droplet (Spaces, S3, or another server) on
the same schedule, since a droplet-level failure would otherwise take the
backups down with it.

### Restore

```bash
# Database
pg_restore -d hitech_bims --clean --if-exists /var/backups/hitech_bims/db_YYYYMMDD.dump

# Media
rsync -avz your-backup-target:/backups/hitech_bims-media/ /home/deploy/hitech_bims/media/
sudo systemctl restart gunicorn
```

---

## 15. Common Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `502 Bad Gateway` from Nginx | Gunicorn isn't running or the socket path is wrong. `sudo systemctl status gunicorn`; `ls -l /run/gunicorn/`. |
| `ImproperlyConfigured: SECRET_KEY environment variable is not set` | `.env` missing or not being read — confirm it's at `PROJECT_PATH/.env` and `EnvironmentFile=` in `gunicorn.service` points at it. |
| `ImproperlyConfigured: ALLOWED_HOSTS environment variable is not set` | Same as above, or `ALLOWED_HOSTS` in `.env` is empty while `DEBUG=False`. |
| Static files 404 | Did `collectstatic` run? Does `deploy/nginx.conf`'s `alias` path match `STATIC_ROOT` (`staticfiles/`)? |
| Cached list data looks stale across requests | The cache is per-process `LocMemCache` — restart Gunicorn workers to clear it, or reduce `CACHES.default.TIMEOUT` in `settings.py`. |
| CSRF failures on forms in production | Add the real origin to `CSRF_TRUSTED_ORIGINS` in `.env` (must include scheme, e.g. `https://...`). |
| Redirect loop on every page | `SECURE_SSL_REDIRECT=True` but Nginx isn't terminating TLS yet (no certbot run) — set `SECURE_SSL_REDIRECT=False` in `.env` until HTTPS is live, or run certbot first. |
| `git reset --hard` in `deploy.sh` fails with local changes | Something was edited directly on the droplet outside of git — `git stash` or `git diff` to inspect before deploying again; the droplet's working tree should always be deploy-managed only. |
| Gunicorn OOM-killed on the 2GB droplet | Lower `WEB_CONCURRENCY` in `.env`, or check `dmesg | grep -i oom`. |
| Deploy job can't SSH in | Verify the `SSH_PRIVATE_KEY` secret matches a key in `deploy`'s `~/.ssh/authorized_keys`, and `DROPLET_HOST`/`DROPLET_USER` secrets are correct. |

Logs to check, in order:

```bash
sudo journalctl -u gunicorn -n 100 --no-pager
tail -100 /var/log/gunicorn/error.log
tail -100 /home/deploy/hitech_bims/logs/error.log
tail -100 /var/log/nginx/hitech_bims.error.log
```

---

## Known Gaps (Not Addressed by This Pass)

Flagged during the production readiness review but intentionally left
untouched — they're pre-existing application concerns, not deployment
configuration, and fixing them risks changing behavior/data outside this
task's scope:

- `BroilerDisease.batch` is declared required in `models.py` but the database
  column is still nullable with existing `NULL` rows — needs a deliberate
  data decision before tightening.
- The `hatchery` app has model changes not yet captured in a migration.
- ~20 stray `print()` debug statements remain across `sales`, `user`,
  `broiler`, `hr`, `inventory`, `purchase`, `account` views.
- `djangorestframework` is installed but unused.
- 66 files under `staticfiles/` are still committed to git from before this
  change — `.gitignore` now excludes the directory going forward, but
  existing tracked files need an explicit one-time cleanup:
  `git rm -r --cached staticfiles && git commit`.
