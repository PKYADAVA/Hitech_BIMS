"""Inline scripts that are actually JavaScript.

A syntax error in a template's ``<script>`` block does not fail anything. The
page still returns 200, the markup still renders, and every handler in that
block silently never binds — so the screen looks right and none of the buttons
do anything. The Growing Charge settlement form spent a commit in that state
over one apostrophe: a string written ``'the batch's records'``, which ends the
literal at the second quote and takes the rest of the file with it.

Nothing caught it. The template renders, the test suite passes, and the only
symptom is somebody pressing ADD and watching nothing happen.

**Why the source and not the rendered page.** There is a per-page version of
this already (``broiler.test_batch_selection.assertScriptsParse``) which renders
a URL and checks what comes out. That is stronger where it applies, and it
applies to three pages, because each one needs a login, a permission and a
fixture. This reads the templates themselves, so it covers all 205 of them and
needs nothing set up.

**The awkward part: Django tags are not JavaScript.** A template's script is
not valid JS until it is rendered, so the tags have to be stood down first, and
there is no single right way to do it:

    order: [[{% if sort %}1, 'asc'{% else %}0, 'asc'], [1, 'asc'{% endif %}]]

Strip the tags and both branches run together into nonsense; either branch on
its own is fine. And ``{{ x }}`` stands where a number, a bare word or a string
belongs, depending on the line. So each script is tried several ways — each
branch of its conditionals, and each plausible filling for its variables — and
it passes if *any* of them parses. Real breakage, like an unterminated string,
fails every way round, which is what makes the check worth having.

That makes this deliberately lenient: it will not catch a script that is
invalid only in one branch. It catches the thing that actually happens, which
is a quote or a bracket that does not close.
"""
import glob
import io
import json
import os
import re
import shutil
import subprocess

from django.test import SimpleTestCase

#: Inline blocks only — a src= tag has nothing between the tags to check.
SCRIPT = re.compile(r"<script(?![^>]*src=)([^>]*)>(.*?)</script>", re.S)

#: One ``{% if %}…{% else %}…{% endif %}`` containing no nested if, so the
#: innermost is always rewritten first and the outer ones on later passes.
IF_ELSE = re.compile(
    r"{%\s*if\b[^%]*%}((?:(?!{%\s*(?:if|endif)\b).)*?)"
    r"{%\s*else\s*%}((?:(?!{%\s*(?:if|endif)\b).)*?){%\s*endif\s*%}", re.S)

#: What ``{{ x }}`` might be standing in for. A number covers most of it; the
#: empty string covers a tag wedged against a literal; a quoted word covers a
#: tag that is the whole of an argument.
FILLINGS = ("0", "", '"x"')


def _is_javascript(attrs: str) -> bool:
    """Whether this block is script rather than a template or a data island.

    ``type="application/json"`` and ``text/x-template`` blocks are markup and
    data. Parsing those as JavaScript is how a check like this starts crying
    wolf and gets switched off.
    """
    lowered = attrs.lower()
    return "type=" not in lowered or "javascript" in lowered


def _branch(js: str, keep: str) -> str:
    """Resolve every if/else to one side of itself, innermost first."""
    previous = None
    while previous != js:
        previous = js
        js = IF_ELSE.sub(lambda m: m.group(1 if keep == "if" else 2), js)
    return js


def readings(js: str):
    """Every way this script might legitimately come out of the renderer."""
    for keep in ("if", "else"):
        stripped = re.sub(r"{%.*?%}", "", _branch(js, keep), flags=re.S)
        for filling in FILLINGS:
            yield re.sub(r"{{.*?}}", filling, stripped, flags=re.S)


def project_templates():
    for root in ("templates", "*/templates"):
        for path in glob.glob(os.path.join(root, "**", "*.html"), recursive=True):
            if ".venv" in path or "site-packages" in path:
                continue
            yield path.replace("\\", "/")


class InlineScriptTests(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.node = shutil.which("node")

    def broken_among(self, groups):
        """Names whose every reading failed to parse.

        One node process for the lot. Spawning ``node --check`` per template
        cost four minutes on Windows, and almost none of it was checking —
        node starting up two hundred times was the whole bill.
        """
        checker = os.path.join(os.path.dirname(__file__), "check_scripts.js")
        result = subprocess.run([self.node, checker], input=json.dumps(groups),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         "the script checker failed: %s" % result.stderr[:500])
        return json.loads(result.stdout or "[]")

    def parses(self, js: str) -> bool:
        return not self.broken_among({"one": [js]})

    def test_every_template_script_parses(self):
        if not self.node:
            self.skipTest("node is not installed")

        groups = {}
        for path in project_templates():
            source = io.open(path, encoding="utf-8", errors="replace").read()
            blocks = [body for attrs, body in SCRIPT.findall(source)
                      if _is_javascript(attrs)]
            if blocks:
                groups[path] = list(readings("\n;\n".join(blocks)))

        self.assertTrue(groups, "no template inline scripts were found to check")
        broken = sorted(self.broken_among(groups))

        self.assertEqual(broken, [],
                         "these templates contain JavaScript that cannot parse "
                         "— the page will render and none of its handlers will "
                         "bind")

    def test_the_check_can_actually_fail(self):
        """A guard that cannot fail is not a guard.

        The exact shape that got through: an apostrophe inside a
        single-quoted string, which ends the literal early.
        """
        if not self.node:
            self.skipTest("node is not installed")
        broken = "var m = 'the batch's records';"
        self.assertEqual(self.broken_among({"it": list(readings(broken))}), ["it"])

    def test_a_conditional_that_writes_two_different_lines_is_allowed(self):
        """Neither branch is wrong; the two of them concatenated are.

        Taken from chicks_placement_report.html, which is why the branches are
        read separately rather than the tags simply stripped.
        """
        if not self.node:
            self.skipTest("node is not installed")
        js = ("var t = {order: [[{% if sort %}1, 'asc'{% else %}0, 'asc'], "
              "[1, 'asc'{% endif %}]]};")
        self.assertEqual(self.broken_among({"it": list(readings(js))}), [])

    def test_the_branches_run_together_would_not_parse(self):
        """The other half of it: strip the tags and check that alone, and the
        template above is reported as broken when nothing is wrong with it."""
        if not self.node:
            self.skipTest("node is not installed")
        self.assertFalse(self.parses("var t = {order: [[1, 'asc'0, 'asc']]};"))

    def test_a_data_island_is_not_read_as_script(self):
        """JSON in a script tag is data. Parsing it as JavaScript is how a
        check like this starts crying wolf and gets switched off."""
        self.assertFalse(_is_javascript(' type="application/json"'))
        self.assertFalse(_is_javascript(' type="text/x-template"'))
        self.assertTrue(_is_javascript(""))
        self.assertTrue(_is_javascript(' type="text/javascript"'))
