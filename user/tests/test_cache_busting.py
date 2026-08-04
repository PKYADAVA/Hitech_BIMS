"""Versioned static assets carry a stamp newer than their content.

This project serves static files un-hashed and busts caches by hand, with a
`?v=` on each `<link>`/`<script>` in base.html. Manifest hashing was tried and
reverted (see the STORAGES comment in settings), so the stamp is the only
thing standing between an edited stylesheet and a browser that keeps the old
one.

Forgetting the bump is invisible from this side: collectstatic succeeds, the
file on disk is right, a fresh browser shows the change, and only returning
users see the old page.

The check is against the commit that last touched base.html, not against the
date inside the stamp. A date is too coarse — the first version of this test
compared them and passed while the bug was live, because the stylesheet was
edited twice more on the same day it was stamped. base.html is the right
yardstick because it holds every stamp: bumping one necessarily commits
base.html at that moment or later, so an asset committed after it is an asset
whose stamp was not bumped.

Against git rather than mtimes, since git does not preserve mtimes and every
file in a fresh clone would otherwise look newer than its stamp.
"""
import datetime
import pathlib
import re
import shutil
import subprocess

from django.test import SimpleTestCase

BASE = pathlib.Path("templates/base.html")
#: `{% static 'css/x.css' %}?v=20260804b` — the trailing letter marks a
#: same-day re-stamp, which is why the letter has to be allowed for.
VERSIONED = re.compile(r"\{%\s*static '([^']+)'\s*%\}\?v=(\d{8}[a-z]?)")


def last_commit_time(path):
    """Unix time of the commit that last touched ``path``; None if untracked."""
    out = subprocess.run(["git", "log", "-1", "--format=%ct", "--", str(path)],
                         capture_output=True, text=True)
    stamp = out.stdout.strip()
    return int(stamp) if stamp.isdigit() else None


def is_dirty(path):
    """True when `path` has changes not yet committed."""
    out = subprocess.run(["git", "status", "--porcelain", "--", str(path)],
                         capture_output=True, text=True)
    return bool(out.stdout.strip())


def when(unix_time):
    return datetime.datetime.fromtimestamp(unix_time).isoformat(" ", "seconds")


class CacheBustingTests(SimpleTestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git is not available")
        if not BASE.exists():
            self.skipTest("base.html not found")

    def test_every_versioned_asset_exists(self):
        missing = [rel for rel, _ in VERSIONED.findall(BASE.read_text(encoding="utf-8"))
                   if not (pathlib.Path("static") / rel).exists()]
        self.assertEqual(missing, [])

    def test_no_asset_was_changed_without_bumping_its_stamp(self):
        stamped_at = last_commit_time(BASE)
        if stamped_at is None:
            self.skipTest("base.html is not committed yet")

        stale = []
        for rel, _ in VERSIONED.findall(BASE.read_text(encoding="utf-8")):
            source = pathlib.Path("static") / rel
            if not source.exists():
                continue
            # An edit still sitting in the working tree has no commit time at
            # all, so comparing those alone reports OK while the browser is
            # already being served something older. If the asset is dirty,
            # base.html has to be dirty too — that is the bump.
            if is_dirty(source) and not is_dirty(BASE):
                stale.append("%s has uncommitted edits but base.html — which "
                             "holds its ?v= — does not" % rel)
                continue
            changed_at = last_commit_time(source)
            if changed_at is None:
                continue                     # never committed; nothing to compare
            if changed_at > stamped_at:
                stale.append("%s changed at %s, but base.html — which holds its "
                             "?v= — was last committed at %s"
                             % (rel, when(changed_at), when(stamped_at)))

        self.assertEqual(stale, [], "\n".join(
            ["static files edited without bumping ?v= in templates/base.html —"
             " returning browsers will keep the cached copy:"] + stale))

    def test_the_collected_copy_matches_the_source(self):
        """WhiteNoise serves staticfiles/, so an uncollected edit is invisible
        however right the source and the stamp are. Only checkable where
        collectstatic has been run; staticfiles/ is generated."""
        collected_root = pathlib.Path("staticfiles")
        if not collected_root.exists():
            self.skipTest("staticfiles/ not built in this tree")

        differing = []
        for rel, _ in VERSIONED.findall(BASE.read_text(encoding="utf-8")):
            source = pathlib.Path("static") / rel
            collected = collected_root / rel
            if not source.exists() or not collected.exists():
                continue
            if source.read_bytes() != collected.read_bytes():
                differing.append(rel)

        self.assertEqual(differing, [],
                         "run collectstatic — these differ from their source: %s"
                         % ", ".join(differing))
