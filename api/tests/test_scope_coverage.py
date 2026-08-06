"""Every API model is scoped, or is on record as deliberately not.

The gap this closes is the one that has now bitten twice elsewhere: a model
arrives, nothing decides whether it needs a scope, and it defaults to open.
"Nobody chose" and "someone chose not to" looked identical from the code.
"""
from django.test import TestCase

from api.viewsets import (API_SCOPES, UNSCOPED_API_MODELS,
                          registered_api_models)

#: Keys in an API_SCOPES entry that configure the combination rather than name
#: a column — never a path, and never a dimension.
_SETTINGS = {"mode", "nulls"}


class ScopeCoverageTests(TestCase):
    def test_no_api_model_is_silently_unscoped(self):
        unaccounted = sorted(
            registered_api_models() - set(API_SCOPES) - set(UNSCOPED_API_MODELS))
        self.assertEqual(
            unaccounted, [],
            "These API models return every row to anyone who may read them. "
            "Give each a scope in API_SCOPES, or name it in "
            "UNSCOPED_API_MODELS with the reason.")

    def test_the_unscoped_list_stays_honest(self):
        """An entry that has since been scoped, or a model no longer exposed,
        leaves a stale excuse in the code."""
        registered = registered_api_models()
        for label, reason in UNSCOPED_API_MODELS.items():
            with self.subTest(model=label):
                self.assertNotIn(label, API_SCOPES,
                                 "scoped now — drop it from UNSCOPED_API_MODELS")
                self.assertIn(label, registered, "no longer exposed by the API")
                self.assertTrue(reason.strip(), "every exemption needs a reason")

    def test_every_scoped_model_is_actually_exposed(self):
        registered = registered_api_models()
        for label in API_SCOPES:
            with self.subTest(model=label):
                self.assertIn(label, registered)

    def test_scope_paths_resolve_against_the_model(self):
        """A typo in a path is silent: Django raises only when the queryset is
        evaluated, which in production is on a user's request."""
        from django.apps import apps
        from django.core.exceptions import FieldError

        for label, scopes in API_SCOPES.items():
            model = apps.get_model(label)
            for scope, fields in scopes.items():
                if scope in _SETTINGS:
                    continue
                # A dimension may name several columns — a transfer has two
                # ends, and either one puts the row in scope.
                for field in ([fields] if isinstance(fields, str) else fields):
                    with self.subTest(model=label, scope=scope, field=field):
                        try:
                            model.objects.filter(**{f"{field}__in": []}).exists()
                        except FieldError as exc:
                            self.fail(f"{label}.{field} is not a real path: {exc}")

    def test_multi_column_dimensions_only_appear_with_mode_any(self):
        """scope_multi takes one field per dimension and would raise on a
        tuple. Only scope_any expands them, so the two must travel together."""
        for label, scopes in API_SCOPES.items():
            multi = [s for s, f in scopes.items()
                     if s not in _SETTINGS and not isinstance(f, str)]
            if multi:
                with self.subTest(model=label):
                    self.assertEqual(scopes.get("mode"), "any",
                                     f"{label} names several columns for "
                                     f"{multi} but does not use mode=any")

    def test_settings_keys_are_spelled_correctly(self):
        """`nulls` decides whether a row with an empty scope column survives.
        A typo would silently fall back to dropping it, which is the bug the
        flag was added to fix and would look identical to not having it."""
        for label, scopes in API_SCOPES.items():
            with self.subTest(model=label):
                self.assertIn(scopes.get("nulls", "drop"), {"drop", "keep"})
                # And `nulls` only means anything under the default mode.
                if scopes.get("nulls") == "keep":
                    self.assertNotEqual(
                        scopes.get("mode"), "any",
                        f"{label}: mode=any already keeps empty rows, so "
                        f"nulls=keep says nothing")

    def test_modes_are_spelled_correctly(self):
        """`mode` decides AND vs OR. A typo would silently fall back to AND
        and hide the far end of every transfer."""
        for label, scopes in API_SCOPES.items():
            with self.subTest(model=label):
                self.assertIn(scopes.get("mode", "all"), {"all", "any"})

    def test_two_ended_rows_use_any(self):
        """Requiring both ends of a movement to be in scope hides the transfer
        out of the user's own store — the one they most need to see."""
        for label in ("inventory.StockIssue", "inventory.StockReceive"):
            with self.subTest(model=label):
                self.assertEqual(API_SCOPES[label]["mode"], "any")

    def test_the_api_mirrors_the_web_for_the_models_it_scopes(self):
        """The API is the same data by another door; the two disagreeing is
        the bug this map exists to avoid."""
        self.assertEqual(API_SCOPES["hatchery.EggPurchase"],
                         {"mode": "any", "sectors": "warehouse_id"})
        self.assertEqual(API_SCOPES["hatchery.ChickSale"],
                         {"mode": "any", "sectors": "warehouse_id"})
        self.assertEqual(API_SCOPES["inventory.StockIssue"],
                         {"mode": "any", "sectors": "items__warehouse_id",
                          "farms": "items__farm_id"})
