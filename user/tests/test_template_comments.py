"""Template comments that are comments.

Django's ``{# ... #}`` is a single-line token. Spread one over two lines and it
stops being a comment: the template engine prints it, and a note written for
whoever maintains the page appears on the page, in front of whoever is using
it. Nothing raises, nothing logs, and no test fails — the only symptom is
paragraphs of internal commentary sitting in the middle of a screen.

That is exactly what happened to the notification centre's filter bar, and it
reached a user before it reached anybody who could read the template. Multi-line
commentary belongs in ``{% comment %} … {% endcomment %}``, which is a block tag
and behaves.
"""
import glob
import io
import os
import re

from django.test import SimpleTestCase

#: Directories holding templates this project owns. Third-party packages in
#: site-packages are somebody else's problem and are not ours to fix.
TEMPLATE_ROOTS = ("templates", "*/templates")


def project_templates():
    for root in TEMPLATE_ROOTS:
        for path in glob.glob(os.path.join(root, "**", "*.html"), recursive=True):
            if ".venv" in path or "site-packages" in path:
                continue
            yield path.replace("\\", "/")


class SingleLineCommentTests(SimpleTestCase):

    def test_no_template_comment_runs_past_its_own_line(self):
        offenders = []
        for path in project_templates():
            with io.open(path, encoding="utf-8") as handle:
                for number, line in enumerate(handle, start=1):
                    # An opening token with no closing token after it on the
                    # same line. Anything already closed is fine however many
                    # of them a line carries.
                    for match in re.finditer(r"\{#", line):
                        if "#}" not in line[match.end():]:
                            offenders.append("%s:%d" % (path, number))
                            break
        self.assertEqual(
            sorted(offenders), [],
            "these {# #} comments span more than one line, so Django prints "
            "them to the page instead of hiding them — use "
            "{% comment %}…{% endcomment %} instead",
        )

    def test_the_check_can_actually_see_a_bad_comment(self):
        """A guard that cannot fail is not a guard.

        The regex above is the whole test; if it stopped matching, the suite
        would go green with the bug back in place and nobody the wiser.
        """
        line = "  {# a note that carries on\n"
        self.assertTrue(re.search(r"\{#", line) and "#}" not in line)
