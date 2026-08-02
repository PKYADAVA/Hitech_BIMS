"""Template mistakes that render as visible text instead of failing loudly.

A broken template comment does not raise — it prints. The `{# #}` form leaked
onto the letterhead of every report in the ERP, where it sat under the report
title reading "{# Spec 25: a printed report has to say when it was produced...".
Nothing failed; the page just carried a note to the developer on it.
"""
import pathlib
import re

from django.test import SimpleTestCase

SKIP_DIRS = {"staticfiles", ".venv", "venv", "node_modules", "site-packages"}


def project_templates():
    for path in pathlib.Path(".").rglob("*.html"):
        if SKIP_DIRS.isdisjoint(path.parts):
            yield path


class TemplateCommentTests(SimpleTestCase):
    def test_no_single_line_comment_spans_lines(self):
        """`{# #}` is a *single-line* form. Django's lexer matches it with a
        pattern that does not cross a newline, so an opener with no closer on
        the same line is not a comment at all — every line of it is emitted to
        the page. Multi-line prose belongs in `{% comment %}`.
        """
        offenders = []
        for path in project_templates():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            for number, line in enumerate(lines, 1):
                for match in re.finditer(r"\{#", line):
                    if "#}" not in line[match.end():]:
                        offenders.append("%s:%d: %s" % (path, number, line.strip()[:80]))

        self.assertEqual(offenders, [], "\n".join(
            ["unterminated {# #} comments — these render as page text:"] + offenders))
