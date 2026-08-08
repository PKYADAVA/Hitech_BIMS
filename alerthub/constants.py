"""Enumerations shared by the whole business-alert module.

Kept free of model imports so the catalogue, the detectors, the API and the
templates can all read the same names without an import cycle.

Note the deliberate distance from :mod:`alerts.constants`. That module
classifies *what a user did to a row* (create/update/delete) and grades it by
technical severity. This one classifies *what the business needs someone to look
at* and grades it by operational priority. The two vocabularies look similar and
must not be merged: "a record was deleted" and "mortality crossed 1%" are not
points on one scale.
"""
from __future__ import annotations

from django.db import models


class Priority(models.TextChoices):
    """Operational urgency, and the only thing that decides colour anywhere."""

    CRITICAL = "critical", "Critical"
    HIGH = "high", "High"
    MEDIUM = "medium", "Medium"
    LOW = "low", "Low"


#: Priority -> the Bootstrap-ish tone token the templates and CSS key off.
#: Single source: the bell, the centre, the history table and the dashboard
#: widget all read this, so a colour can never mean two things in two places.
PRIORITY_TONE = {
    Priority.CRITICAL: "danger",
    Priority.HIGH: "warning",
    Priority.MEDIUM: "info",
    Priority.LOW: "success",
}

#: Priority -> hex, for the places CSS variables cannot reach (inline SVG,
#: email bodies later). Matches PRIORITY_TONE's intent: red/orange/blue/green.
PRIORITY_COLOR = {
    Priority.CRITICAL: "#dc2626",
    Priority.HIGH: "#ea580c",
    Priority.MEDIUM: "#2563eb",
    Priority.LOW: "#16a34a",
}

#: Sort weight — lower is more urgent. Used for ordering feeds by urgency then
#: recency, which is not the same as ordering by the priority *string*.
PRIORITY_RANK = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}


class Module(models.TextChoices):
    """Business area an alert belongs to — the spec's nine groups.

    These are alert-module labels, not Django app labels. "Production" spans
    broiler batches and daily entries; "Feed" spans inventory items and farm
    consumption. Tying them to app labels would force a rename the day a model
    moves apps.
    """

    PRODUCTION = "production", "Production"
    FEED = "feed", "Feed"
    HATCHERY = "hatchery", "Hatchery"
    HEALTH = "health", "Health"
    INVENTORY = "inventory", "Inventory"
    PURCHASE = "purchase", "Purchase"
    SALES = "sales", "Sales"
    FINANCE = "finance", "Finance"
    HR = "hr", "HR"
    SYSTEM = "system", "System"


#: Module -> Font Awesome icon, so an alert looks the same everywhere it renders.
MODULE_ICON = {
    Module.PRODUCTION: "fa-solid fa-kiwi-bird",
    Module.FEED: "fa-solid fa-wheat-awn",
    Module.HATCHERY: "fa-solid fa-egg",
    Module.HEALTH: "fa-solid fa-syringe",
    Module.INVENTORY: "fa-solid fa-boxes-stacked",
    Module.PURCHASE: "fa-solid fa-cart-shopping",
    Module.SALES: "fa-solid fa-file-invoice-dollar",
    Module.FINANCE: "fa-solid fa-indian-rupee-sign",
    Module.HR: "fa-solid fa-users",
    Module.SYSTEM: "fa-solid fa-server",
}


class Channel(models.TextChoices):
    """Delivery routes. Only IN_APP is wired; the rest are configurable now and
    delivered when a provider is connected.

    They are listed here rather than added later because the Alert Configuration
    master has to store the operator's intent ("email me the critical ones")
    before the transport exists — otherwise switching email on later means
    re-deciding every rule. :data:`LIVE_CHANNELS` is what the sender actually
    honours, so nothing silently claims to have sent an SMS.
    """

    IN_APP = "in_app", "In-App"
    PUSH = "push", "Mobile Push"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"


#: Channels with a working transport today. The dispatcher refuses anything not
#: in here and records the intent instead, so the history stays honest.
#:
#: Push joined in-app once ``alerthub.push`` was wired to the Expo sender the
#: mobile app already registers its device tokens with — both halves existed
#: and had simply never been joined.
LIVE_CHANNELS = frozenset({Channel.IN_APP, Channel.PUSH})


class Operator(models.TextChoices):
    """How a measured value is compared with the rule's threshold."""

    GT = "gt", "Greater than"
    GTE = "gte", "Greater than or equal"
    LT = "lt", "Less than"
    LTE = "lte", "Less than or equal"
    EQ = "eq", "Equal to"


#: Operator -> the symbol shown in the config master and in alert messages.
OPERATOR_SYMBOL = {
    Operator.GT: ">",
    Operator.GTE: "≥",
    Operator.LT: "<",
    Operator.LTE: "≤",
    Operator.EQ: "=",
}


def compare(value, operator, threshold) -> bool:
    """Apply ``operator`` to ``value`` and ``threshold``.

    Returns False when either side is None rather than raising: a detector that
    could not measure something has not detected a breach, and a missing weight
    reading must not fire a "low body weight" alert.
    """
    if value is None or threshold is None:
        return False
    checks = {
        Operator.GT: lambda a, b: a > b,
        Operator.GTE: lambda a, b: a >= b,
        Operator.LT: lambda a, b: a < b,
        Operator.LTE: lambda a, b: a <= b,
        Operator.EQ: lambda a, b: a == b,
    }
    check = checks.get(operator)
    return bool(check and check(value, threshold))
