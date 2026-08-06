"""A screen wears the same icon in the app as it does on the web.

The two sets were chosen independently and had drifted apart — Farms was a
tractor on the web and a house on the phone, Hatch Settings an egg and a
gear, Suppliers a lorry and a factory. Nothing breaks when they disagree,
which is why it went unnoticed; it just stops being one product.

The web draws Font Awesome from the sub-nav template and the app draws
MaterialCommunityIcons, so the two can never be the same string. FA_TO_MCI is
the agreed translation, and this checks the app actually uses it. A screen
whose web icon has no translation is reported rather than skipped, so adding a
tab with a new glyph asks for a decision instead of silently drifting.
"""
import json
import pathlib
import re

from django.conf import settings
from django.test import SimpleTestCase

from user.services.mobile_access import PHONE_REPORTS, PHONE_SCREENS

#: Font Awesome glyph used on the web -> the MaterialCommunityIcons equivalent
#: drawn by the app. Every value is checked against the bundled glyph map below,
#: so a typo here fails rather than rendering a fallback circle.
FA_TO_MCI = {
    "fa-arrow-down-to-bracket": "tray-arrow-down",
    "fa-arrow-up-from-bracket": "tray-arrow-up",
    "fa-book": "book-open-variant",
    "fa-box": "package-variant-closed",
    "fa-building": "office-building",
    "fa-calendar-alt": "calendar",
    "fa-calendar-day": "calendar-today",
    "fa-car-side": "car-side",
    "fa-cash-register": "cash-register",
    "fa-chart-bar": "chart-bar",
    "fa-chart-line": "chart-line",
    "fa-clock-rotate-left": "history",
    "fa-code-branch": "source-branch",
    "fa-comment-sms": "message-text",
    "fa-dna": "dna",
    "fa-dove": "bird",
    "fa-egg": "egg",
    "fa-file-alt": "file-document-outline",
    "fa-file-contract": "file-sign",
    "fa-file-invoice": "file-document",
    "fa-file-invoice-dollar": "file-document-outline",
    "fa-folder": "folder",
    "fa-gear": "cog",
    "fa-hand-holding-dollar": "hand-coin",
    "fa-id-badge": "badge-account",
    "fa-kiwi-bird": "bird",
    "fa-layer-group": "layers",
    "fa-list-alt": "format-list-bulleted",
    "fa-location-dot": "map-marker",
    "fa-map-marked-alt": "map-marker-radius",
    "fa-map-marker-alt": "map-marker",
    "fa-money-bill-wave": "cash",
    "fa-percentage": "percent",
    "fa-receipt": "receipt",
    "fa-right-left": "swap-horizontal",
    "fa-seedling": "sprout",
    "fa-ruler": "ruler",
    "fa-shopping-basket": "basket",
    "fa-sitemap": "sitemap",
    "fa-sliders-h": "tune",
    "fa-syringe": "needle",
    "fa-table-cells": "grid",
    "fa-tag": "tag",
    "fa-tags": "tag-multiple",
    "fa-temperature-high": "thermometer-high",
    "fa-tractor": "tractor",
    "fa-truck": "truck",
    "fa-truck-loading": "truck-delivery",
    "fa-university": "bank",
    "fa-user": "account",
    "fa-user-check": "account-check",
    "fa-user-group": "account-group",
    "fa-user-plus": "account-plus",
    "fa-user-tie": "account-tie",
    "fa-user-times": "account-remove",
    "fa-users": "account-group",
    "fa-users-cog": "account-cog",
    "fa-virus": "virus",
    "fa-warehouse": "warehouse",
    "fa-wheat-awn": "grain",
}

MOBILE = pathlib.Path(settings.BASE_DIR) / "mobile"
SUBNAV = pathlib.Path(settings.BASE_DIR) / "templates" / "_subnav.html"
CATALOG = MOBILE / "src" / "config" / "catalog.ts"
GLYPHMAP = (MOBILE / "node_modules" / "@expo" / "vector-icons" / "build" / "vendor"
            / "react-native-vector-icons" / "glyphmaps" / "MaterialCommunityIcons.json")


def web_tab_icons():
    """tab code -> Font Awesome glyph, read off the sub-nav template."""
    icons = {}
    for line in SUBNAV.read_text(encoding="utf-8").splitlines():
        tab = re.search(r"'([a-z_]+)' in allowed_tabs", line)
        icon = re.search(r'<i class="(fa[s-][^"]*?)\s*(?:me-1)?"', line)
        if tab and icon:
            cleaned = re.sub(r"\s*(me-1|fa-solid|fas)\s*", " ", icon.group(1)).strip()
            icons[tab.group(1)] = cleaned
    return icons


def app_icons():
    """resource/report key -> the icon string the app draws."""
    source = CATALOG.read_text(encoding="utf-8")
    return dict(re.findall(r'key: "([a-z0-9-]+)",.*?icon: "([^"]+)"', source, re.S))


class IconParityTests(SimpleTestCase):
    def setUp(self):
        if not CATALOG.exists():
            self.skipTest("mobile client not present")

    def test_the_translation_table_names_real_glyphs(self):
        """A typo here would draw the fallback circle, which looks deliberate."""
        if not GLYPHMAP.exists():
            self.skipTest("mobile dependencies not installed")
        glyphs = set(json.loads(GLYPHMAP.read_text(encoding="utf-8")))
        unknown = sorted({v for v in FA_TO_MCI.values() if v not in glyphs})
        self.assertEqual(unknown, [])

    def test_every_screen_wears_the_web_s_icon(self):
        web, app = web_tab_icons(), app_icons()
        wrong = []
        for key, tab in list(PHONE_SCREENS) + list(PHONE_REPORTS):
            fa = web.get(tab)
            if not fa:
                continue                      # no web tab, nothing to match
            expected = FA_TO_MCI.get(fa)
            if expected is None:
                wrong.append("%s: web uses %s, which has no agreed MCI "
                             "equivalent - add one to FA_TO_MCI" % (key, fa))
                continue
            actual = app.get(key)
            if actual != expected:
                wrong.append("%s: web %s -> expected %s, app draws %s"
                             % (key, fa, expected, actual))
        self.assertEqual(wrong, [], "\n".join(["icons disagree with the web:"] + wrong))
