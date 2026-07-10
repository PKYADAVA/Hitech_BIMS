"""Gunicorn configuration for production deployment.

Usage (see deploy/gunicorn.service):
    gunicorn -c gunicorn.conf.py Hitech_BIMS.wsgi:application
"""

import multiprocessing
import os

# --- Networking ---
# Bind to a unix socket by default - Nginx proxies to it directly (see deploy/nginx.conf).
# Override with GUNICORN_BIND to bind a TCP port instead (e.g. during local testing).
bind = os.getenv("GUNICORN_BIND", "unix:/run/gunicorn/hitech_bims.sock")

# --- Workers ---
# Sized conservatively for a 2GB droplet that also runs PostgreSQL, Redis, Nginx
# and a Celery worker side by side. Override with WEB_CONCURRENCY if the droplet
# is resized.
workers = int(os.getenv("WEB_CONCURRENCY", str(min(3, multiprocessing.cpu_count() * 2 + 1))))
worker_class = "sync"
threads = int(os.getenv("GUNICORN_THREADS", "2"))

# --- Timeouts ---
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
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
