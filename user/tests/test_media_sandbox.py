"""No test may delete the project's own media folder.

One did. ``account.test_petty_expense.EndpointTests`` removed
``settings.MEDIA_ROOT`` in its teardown, and without an override that is the
working copy's ``media/`` -- so running the account suite deleted every
upload a developer had: bills, farm photographs, odometer shots, KYC scans.
Nothing in the output said so; the files were simply gone, and the database
went on pointing at them.

The fix was to delete a named temporary directory instead. This is the fence
around it: a test that removes a tree must not be able to name the real media
root, whether by reading the setting or by writing the path out.
"""
from __future__ import annotations

import ast
import pathlib

from django.test import SimpleTestCase

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Where Django's own tooling and third-party code live: not ours to police.
SKIP = {".venv", "node_modules", "staticfiles", "media", ".git", "mobile"}


def _test_files():
    for path in ROOT.rglob("test*.py"):
        if any(part in SKIP for part in path.parts):
            continue
        yield path


class MediaSandboxTests(SimpleTestCase):
    def test_no_test_removes_a_tree_it_read_from_the_settings(self):
        """``rmtree(settings.MEDIA_ROOT)`` is the shape of the bug.

        A test that wants a media folder overrides ``MEDIA_ROOT`` with a
        temporary directory and removes *that*, by name. Reading the setting
        back means removing whatever happens to be configured, which in a
        working copy is the developer's own uploads.
        """
        offenders = []
        for path in _test_files():
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "rmtree" not in source:
                continue
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name != "rmtree" or not node.args:
                    continue
                first = node.args[0]
                # settings.MEDIA_ROOT, or anything read off `settings`.
                reads_settings = (
                    isinstance(first, ast.Attribute)
                    and isinstance(first.value, ast.Name)
                    and first.value.id == "settings"
                )
                if reads_settings:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

        self.assertEqual(
            offenders, [],
            "A test removes a directory read from the settings. Override "
            "MEDIA_ROOT with a temporary directory and delete that path by "
            "name instead:\n  " + "\n  ".join(offenders))

    def test_no_test_names_the_projects_media_folder(self):
        """Nor by spelling the path out."""
        offenders = []
        for path in _test_files():
            source = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(source.splitlines(), start=1):
                if "rmtree" not in line:
                    continue
                if '"media"' in line or "'media'" in line or "/media" in line:
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
        self.assertEqual(offenders, [],
                         "A test removes something called media:\n  "
                         + "\n  ".join(offenders))
