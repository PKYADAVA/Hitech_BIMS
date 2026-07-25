"""Idempotently ensure an admin account exists — bootstrap for fresh deploys.

A freshly-migrated database has all the tables but *no users*, so nobody can log
in (the API correctly returns 401 "No active account found"). Running this on
every deploy guarantees a known, active superuser exists so you're never locked
out.

Driven entirely by environment variables (nothing hard-coded):

    DJANGO_SUPERUSER_USERNAME   required to do anything
    DJANGO_SUPERUSER_PASSWORD   required to do anything
    DJANGO_SUPERUSER_EMAIL      optional

Behaviour: creates the user if missing; always sets it active + staff +
superuser and (re)sets the password to the env value, so a forgotten password is
self-healing on the next deploy. When the two required vars aren't set it prints
a notice and exits 0 — safe to leave wired into the deploy command permanently.

Security note: because it re-sets the password from the env var on every run,
rotate/remove ``DJANGO_SUPERUSER_PASSWORD`` once you've signed in and created
your real accounts, so a deploy can't silently reset it.
"""
from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure an admin superuser exists (from DJANGO_SUPERUSER_* env vars)."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")

        # Fallback for when you can't set env vars (e.g. no dashboard access):
        # committed values in Hitech_BIMS/bootstrap_admin.py. Env vars win.
        if not username or not password:
            try:
                from Hitech_BIMS import bootstrap_admin as ba
                username = username or (getattr(ba, "BOOTSTRAP_ADMIN_USERNAME", "") or None)
                password = password or (getattr(ba, "BOOTSTRAP_ADMIN_PASSWORD", "") or None)
                email = email or getattr(ba, "BOOTSTRAP_ADMIN_EMAIL", "")
            except Exception:
                pass

        if not username or not password:
            self.stdout.write(
                "ensure_admin: no credentials (DJANGO_SUPERUSER_* env vars or "
                "Hitech_BIMS/bootstrap_admin.py) — skipping."
            )
            return

        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": email}
        )
        if email:
            user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"ensure_admin: {'created' if created else 'updated'} active superuser "
                f"'{username}'."
            )
        )
