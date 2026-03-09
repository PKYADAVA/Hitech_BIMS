# Hitech BIMS - Claude Code Guide

## Project Overview
Django-based Business Information Management System (BIMS) for broiler/poultry operations.

## Tech Stack
- **Framework:** Django 4.2.6
- **Database:** PostgreSQL (psycopg3), via `dj_database_url` in production
- **Task Queue:** Celery 5.4 with Redis broker
- **Admin Theme:** django-jazzmin
- **API:** Django REST Framework
- **Server:** Gunicorn (production), Django dev server (development)

## Project Structure
```
Hitech_BIMS/         # Django project config (settings, urls, celery, wsgi)
broiler/             # Broiler/poultry management app
inventory/           # Inventory management app
hr/                  # Human resources app
sales/               # Sales app
purchase/            # Purchasing app
account/             # Accounting app
user/                # Authentication & user management app
templates/           # Global templates directory
static/              # Static source files
staticfiles/         # Collected static files (STATIC_ROOT)
logs/                # Log files (info.log, celery.log)
```

## Environment Variables
Configure via `.env` file:
```
SECRET_KEY=
DEBUG=True
DEVELOPMENT_MODE=True
DB_ENGINE=django.db.backends.postgresql
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=5432
DATABASE_URL=          # Used in production (non-dev mode)
REDIS_URL=redis://localhost:6379/0
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
ALLOWED_HOSTS=*
```

## Common Commands
```bash
# Run development server
python manage.py runserver

# Run migrations
python manage.py makemigrations
python manage.py migrate

# Collect static files
python manage.py collectstatic

# Start Celery worker
celery -A Hitech_BIMS worker -l info

# Start Celery Beat (scheduler)
celery -A Hitech_BIMS beat -l info
```

## Key Conventions
- Each app has its own `urls.py`, `models.py`, `views.py`, `admin.py`, `templates/` dir
- All app URLs are included at root path (`""`) in the main `urls.py`
- Authentication redirects: login → `/login/`, post-login → `/`, post-logout → `/login/`
- Media files served in DEBUG mode only
- Logging: rotating file handler at `logs/info.log` (1MB, 10 backups) + console

## Notes
- `DEVELOPMENT_MODE=True` uses individual DB env vars; `False` uses `DATABASE_URL`
- Production security settings (HSTS, SSL, secure cookies) auto-enable when `DEBUG=False`
- Never commit `.env` or leave `print()` debug statements in `settings.py`
