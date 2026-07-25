"""TEMPORARY first-login credentials — for when you can't set env vars.

Use this ONLY if you have no access to the DigitalOcean dashboard (env vars /
console). On every deploy, `python manage.py ensure_admin` reads these and
creates — and keeps active — a superuser you can log in with.

HOW TO USE
    1. Fill in a username + a strong password below.
    2. Commit & push — DigitalOcean auto-deploys and creates the admin.
    3. Log in to the app with those credentials.
    4. Change your password inside the app, then BLANK THESE OUT (set back to
       "") and push again so the deploy stops re-applying them.

SECURITY WARNING
    A password here is committed to git (and re-applied on every deploy). Treat
    it as throwaway, rotate it in-app immediately after first login, and clear
    it here. Never leave a real, long-term password in this file. Prefer the
    DJANGO_SUPERUSER_* environment variables whenever you can reach the
    dashboard — those override anything here.
"""

BOOTSTRAP_ADMIN_USERNAME = ""
BOOTSTRAP_ADMIN_PASSWORD = ""
BOOTSTRAP_ADMIN_EMAIL = ""
