"""Gunicorn configuration for production deployment.

Usage (see deploy/gunicorn.service):
    gunicorn -c gunicorn.conf.py Hitech_BIMS.wsgi:application
"""

import os

# --- Networking ---
# Bind to a unix socket by default - Nginx proxies to it directly (see deploy/nginx.conf).
# Override with GUNICORN_BIND to bind a TCP port instead (e.g. during local testing).
bind = os.getenv("GUNICORN_BIND", "unix:/run/gunicorn/hitech_bims.sock")

# --- Workers ---
# Sized from AVAILABLE MEMORY, not CPU count. Two reasons this app is
# memory-bound rather than CPU-bound:
#   1. Each worker is a full copy of a large Django app (15 local apps plus
#      jazzmin, admin, DRF, drf-spectacular, django-import-export, and openpyxl
#      pulled in at module scope by account/views.py). Steady-state RSS lands
#      around 200MB per worker and spikes higher during spreadsheet exports.
#   2. multiprocessing.cpu_count() is actively misleading in a container: on
#      DigitalOcean App Platform it reports the HOST node's CPU count (8-16),
#      not this container's share, so any cpu_count()-derived default oversizes
#      the pool and gets the container OOM-killed.
# WEB_CONCURRENCY still wins if set — but nothing sets it for us here, since
# it's a Heroku convention that App Platform does not populate.

_WORKER_BUDGET_MB = int(os.getenv("GUNICORN_WORKER_MB", "320"))
# Held back for the master (a full app copy too, under preload_app), the OS,
# and page cache.
_RESERVED_MB = int(os.getenv("GUNICORN_RESERVED_MB", "192"))
_MAX_WORKERS = 8


def _container_memory_mb():
    """Return this container's memory cap in MB, or None if unconstrained.

    Reads the cgroup limit rather than total host RAM: inside a container the
    host figure is irrelevant and far too large. Handles cgroup v2 (memory.max,
    literal "max" when unlimited) and v1 (memory.limit_in_bytes, a sentinel
    near 2**63 when unlimited).
    """
    for path in ("/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as fh:
                raw = fh.read().strip()
        except OSError:
            continue
        if raw == "max":
            return None
        try:
            value = int(raw)
        except ValueError:
            continue
        # v1 reports an absurd sentinel instead of "max" when uncapped.
        if value <= 0 or value >= 2 ** 62:
            return None
        return value // (1024 * 1024)
    return None


def _default_workers():
    memory_mb = _container_memory_mb()
    if memory_mb is None:
        # Not in a memory-capped container (bare droplet, local dev). Keep the
        # old conservative default rather than guessing from host RAM.
        return 3
    usable = memory_mb - _RESERVED_MB
    return max(1, min(_MAX_WORKERS, usable // _WORKER_BUDGET_MB))


workers = int(os.getenv("WEB_CONCURRENCY", str(_default_workers())))
worker_class = "sync"
threads = int(os.getenv("GUNICORN_THREADS", "2"))

# --- Timeouts ---
# 120s, not Gunicorn's 30s default: several forms in this app (farm pictures,
# agreement/cheque uploads) accept multiple files and can legitimately take a
# while on a slow connection.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEPALIVE", "5"))

# --- Worker lifecycle ---
# Recycle workers periodically to bound memory growth from any leaks; jitter
# avoids every worker restarting at the same moment.
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# Load the application once before forking workers - faster worker startup and
# lower memory usage (shared copy-on-write pages). Safe here since the app
# holds no pre-fork state that requires per-worker isolation.
preload_app = True

# Worker heartbeat files default to a location that can be a slow, disk-backed
# filesystem on some container platforms, which can get workers incorrectly
# killed as unresponsive under load. /dev/shm (tmpfs, in-memory) avoids that -
# used when available (Linux containers/droplets, incl. App Platform); falls
# back to Gunicorn's own default elsewhere (e.g. local macOS/Windows dev).
if os.path.isdir("/dev/shm"):
    worker_tmp_dir = "/dev/shm"

# --- Logging ---
# Default to stdout/stderr ("-") so this works unmodified on any platform that
# captures process output itself (DigitalOcean App Platform, Heroku-style
# buildpacks, `docker logs`, journald via systemd's own stdout capture, etc.) -
# an arbitrary /var/log path is not guaranteed to exist or be writable there.
# Set GUNICORN_LOG_DIR explicitly (see deploy/gunicorn.service) to opt into
# dedicated log files instead, e.g. for the systemd/Droplet deployment path
# described in DEPLOYMENT.md.
LOG_DIR = os.getenv("GUNICORN_LOG_DIR")
accesslog = os.path.join(LOG_DIR, "access.log") if LOG_DIR else "-"
errorlog = os.path.join(LOG_DIR, "error.log") if LOG_DIR else "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
capture_output = True

# --- Process naming ---
proc_name = "hitech_bims"


# --- Deploy-time bootstrap ------------------------------------------------
# Run migrations and the idempotent seed commands ONCE, in the Gunicorn master,
# before any worker forks. Gunicorn auto-loads this file, so this happens on
# every deploy even if the platform's run command is just `gunicorn ...` — e.g.
# a DigitalOcean App Platform Run Command that overrides the Procfile.
#
# These deliberately live here rather than in the Procfile. Chaining them in
# the Procfile spawns a separate full Django process per command, sequentially,
# right as the container boots — a memory spike at exactly the moment the
# platform health check is watching, on top of gunicorn's own footprint. Here
# they reuse the single already-initialised master process, and migrate is
# guaranteed to complete before the seeds touch the schema.
#
# Set RUN_MIGRATIONS_ON_START=0 to skip the whole bootstrap (e.g. if you move
# it to a dedicated PRE_DEPLOY job — see .do/app.yaml).
def on_starting(server):
    server.log.info(
        "on_starting: %d worker(s), %d thread(s); container memory cap: %s",
        workers, threads,
        f"{_container_memory_mb()}MB" if _container_memory_mb() else "uncapped",
    )

    if os.getenv("RUN_MIGRATIONS_ON_START", "1") not in ("1", "true", "True"):
        return
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hitech_BIMS.settings")

    import django
    django.setup()
    from django.core.management import call_command

    try:
        server.log.info("on_starting: applying database migrations…")
        call_command("migrate", interactive=False, verbosity=1)
        server.log.info("on_starting: migrations up to date.")
    except Exception:
        # Fail the boot loudly rather than serve a half-migrated schema — the
        # platform keeps the previous (healthy) deploy running on a failed one.
        server.log.exception("on_starting: database migration failed")
        raise

    # Seeds are best-effort, matching the `|| true` they carried in the
    # Procfile: a failure here should not block an otherwise-migrated deploy.
    for command in ("ensure_admin", "seed_sms_templates"):
        try:
            call_command(command)
        except Exception:
            server.log.exception("on_starting: %s failed (continuing)", command)
