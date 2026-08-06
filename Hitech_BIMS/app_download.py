"""The share link for the Android app.

One address to hand to staff — ``/app/`` — rather than a link to a file whose
name changes with every release. The page finds the current build; the address
does not move.

Deliberately public. Whoever is installing the app has no session on their
phone's browser yet, and gating the download behind a login they can only reach
*through* the app is a circle. The APK carries no credentials of its own: it
asks for the same login the ERP does, against the same server, so publishing it
gives away nothing that the login page does not.

Where the build lives is a deployment question, not a code one — see
``APK_DOWNLOAD_URL`` in settings.
"""
import os

from django.conf import settings
from django.shortcuts import render


def _static_apk():
    """The newest APK collected into ``static/app/``, or None.

    A fallback for a deployment with no object storage: files under ``static``
    are part of the build, so they survive a deploy where anything written at
    runtime does not.
    """
    folder = os.path.join(settings.BASE_DIR, "static", "app")
    try:
        names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".apk"))
    except OSError:
        return None
    if not names:
        return None
    newest = names[-1]
    size = os.path.getsize(os.path.join(folder, newest))
    return {"url": f"{settings.STATIC_URL}app/{newest}", "name": newest,
            "size_mb": round(size / (1024 * 1024), 1)}


def app_download(request):
    """GET /app/ — install the Android app."""
    configured = (settings.APK_DOWNLOAD_URL or "").strip()
    local = None if configured else _static_apk()

    url = configured or (local["url"] if local else "")
    version = settings.APK_VERSION or ""
    if not version and local:
        # "hitech-bims-v0.2.0.apk" -> "0.2.0", when nobody set it explicitly.
        stem = local["name"].rsplit(".", 1)[0]
        version = stem.split("-v")[-1] if "-v" in stem else ""

    # Chrome refuses a download that leaves an HTTPS page for an HTTP one, and
    # says so in a strip at the bottom of the window that people miss entirely.
    # The report that comes back is "the download does nothing", which is a
    # long way from the cause, so the page names it instead.
    insecure = url.startswith("http://") and request.is_secure()

    return render(request, "app_download.html", {
        "download_url": url,
        "version": version,
        "size_mb": local["size_mb"] if local else None,
        "host": request.get_host(),
        "insecure_link": insecure,
    })
