"""Versioned static assets carry a stamp at least as new as their content.

This project serves static files un-hashed and busts caches by hand, with a
`?v=YYYYMMDD` on each `<link>`/`<script>` in base.html. Manifest hashing was
tried and reverted (see the STORAGES comment in settings), so the stamp is the
only thing standing between an edited stylesheet and a browser that keeps the
old one.

Forgetting the bump is invisible: collectstatic succeeds, the file on disk is
right, a fresh browser shows the change, and only returning users see the old
page. It cost a round of "why does it still look the same?" to find, hence
this.

Compared against each file's last commit date rather than its mtime: git does
not preserve mtimes, so in a fresh clone every file looks newer than every
stamp. Skipped where git history is not available.
"""
import datetime
import pathlib
import re
import shutil
import subprocess

from django.test import SimpleTestCase

BASE = pathlib.Path("templates/base.html")
#: `{% static 'css/x.css' %}?v=20260804` — the trailing letter some stamps
#: carry (20260731b) is a same-day rebuild and is ignored for the comparison.
VERSIONED = re.compile(r"\{%\s*static '([^']+)'\s*%\}\?v=(\d{8})[a-z]?")


def last_commit_date(path):
    out = subprocess.run(["git", "log", "-1", "--format=%cd",
                          "--date=format:%Y%m%d", "--", str(path)],
                         capture_output=True, text=True)
    stamp = out.stdout.strip()
    return datetime.datetime.strptime(stamp, "%Y%m%d").date() if stamp else None


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
        """A file committed after the stamp it is served under is a file
        returning users are still seeing the old copy of."""
        stale = []
        for rel, stamp in VERSIONED.findall(BASE.read_text(encoding="utf-8")):
            source = pathlib.Path("static") / rel
            if not source.exists():
                continue
            committed = last_commit_date(source)
            if committed is None:
                continue                     # never committed; nothing to compare
            stamped = datetime.datetime.strptime(stamp, "%Y%m%d").date()
            if committed > stamped:
                stale.append("%s: last changed %s but served as ?v=%s"
                             % (rel, committed, stamp))

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
