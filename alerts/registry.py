"""Central registry deciding *which* models are audited and *how*.

Two registration styles, both optional:

    from alerts.registry import register_alert

    @register_alert(severity="warning", event_prefix="employee")
    class Employee(models.Model): ...

or declaratively in settings::

    ALERT_SETTINGS = {"TRACK_ALL_MODELS": True, "IGNORE_MODELS": ["hr.Payslip"]}

With ``TRACK_ALL_MODELS`` on (the default), :meth:`autodiscover` sweeps every
installed concrete model — minus framework noise and explicit ignores — so a
newly-added app is audited with zero wiring. Per-model overrides supplied via
the decorator still win. This is the mechanism that keeps future maintenance
near zero.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from django.apps import apps as django_apps
from django.db import models

from .conf import config
from .constants import Severity
from .utils import model_label

logger = logging.getLogger(__name__)


@dataclass
class ModelRule:
    """Per-model audit configuration."""

    model: type[models.Model]
    severity: str = Severity.INFO
    event_prefix: str = ""          # e.g. "order" -> order_created/updated/...
    ignore_fields: set[str] = field(default_factory=set)
    track_create: bool = True
    track_update: bool = True
    track_delete: bool = True
    track_m2m: bool = True
    audit: bool = True              # write AuditLog rows for this model

    @property
    def label(self) -> str:
        return model_label(self.model)

    def prefix(self) -> str:
        return self.event_prefix or self.model._meta.model_name


class AlertRegistry:
    """Holds :class:`ModelRule` objects and connects/disconnects signals."""

    def __init__(self) -> None:
        self._rules: dict[str, ModelRule] = {}
        self._connected = False

    # -- registration ------------------------------------------------------
    def register(self, model: type[models.Model], **options) -> ModelRule:
        rule = ModelRule(model=model, **options)
        self._rules[rule.label] = rule
        if self._connected:
            # Late registration (e.g. from a test) wires immediately.
            from . import signals

            signals.connect_model(rule)
        return rule

    def unregister(self, model: type[models.Model]) -> None:
        label = model_label(model)
        rule = self._rules.pop(label, None)
        if rule and self._connected:
            from . import signals

            signals.disconnect_model(rule)

    def get_rule(self, model: type[models.Model]) -> Optional[ModelRule]:
        return self._rules.get(model_label(model))

    def is_registered(self, model: type[models.Model]) -> bool:
        return model_label(model) in self._rules

    def rules(self) -> list[ModelRule]:
        return list(self._rules.values())

    # -- discovery ---------------------------------------------------------
    def _is_ignored(self, model: type[models.Model]) -> bool:
        meta = model._meta
        if meta.abstract or meta.proxy or meta.auto_created:
            return True
        if meta.app_label in config.IGNORE_APP_LABELS:
            return True
        if model_label(model).lower() in config.IGNORE_MODELS:
            return True
        return False

    def autodiscover(self) -> None:
        """Populate rules for every eligible model when TRACK_ALL_MODELS is on.

        Models already registered via the decorator are left untouched so
        their custom options survive. auth.User is always registered (its app
        label is otherwise ignored) because user CRUD is high-value.
        """
        if not config.TRACK_ALL_MODELS:
            return
        for model in django_apps.get_models():
            if self._is_ignored(model) or self.is_registered(model):
                continue
            self.register(model)

        # auth.User is worth auditing even though the ``auth`` app is ignored.
        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        if not self.is_registered(user_model):
            self.register(user_model, event_prefix="user", severity=Severity.WARNING)

    # -- signal wiring -----------------------------------------------------
    def connect(self) -> None:
        from . import signals

        for rule in self._rules.values():
            signals.connect_model(rule)
        self._connected = True
        logger.info("alerts: connected signals for %d models", len(self._rules))

    def disconnect(self) -> None:
        from . import signals

        for rule in self._rules.values():
            signals.disconnect_model(rule)
        self._connected = False


registry = AlertRegistry()

# Pending decorator registrations captured before app-ready. The decorator can
# be applied at import time (module load) which may run before ``ready()``;
# storing options on the class and replaying them keeps ordering irrelevant.
_PENDING: list[tuple[type[models.Model], dict]] = []


def register_alert(model: Optional[type[models.Model]] = None, **options):
    """Class decorator to register a model for auditing with overrides.

    Usable bare (``@register_alert``) or parameterised
    (``@register_alert(severity="critical")``).
    """

    def _wrap(cls: type[models.Model]) -> type[models.Model]:
        registry.register(cls, **options)
        return cls

    if model is not None and isinstance(model, type):
        return _wrap(model)
    return _wrap
