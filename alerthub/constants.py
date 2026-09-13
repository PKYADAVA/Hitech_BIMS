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
#:
#: Green is deliberately not in here. It used to mark Low, and an alert that
#: has been *resolved* is now green everywhere — which would have made green
#: mean both "nothing much" and "dealt with" on the same dashboard. Low reads
#: as informational, so it takes blue and Medium moves to amber, which is what
#: a warning looks like to everyone who has ever seen one.
PRIORITY_TONE = {
    Priority.CRITICAL: "danger",
    Priority.HIGH: "warning",
    Priority.MEDIUM: "warning",
    Priority.LOW: "info",
}

#: Priority -> hex, for the places CSS variables cannot reach (inline SVG,
#: email bodies later). Red / orange / amber / blue, with green kept back for
#: resolution. The two tones above collapse to one Bootstrap word; these do
#: not, and the CSS keys off the priority name rather than the tone.
PRIORITY_COLOR = {
    Priority.CRITICAL: "#dc2626",
    Priority.HIGH: "#ea580c",
    Priority.MEDIUM: "#d97706",
    Priority.LOW: "#2563eb",
}

#: The state an alert is in, once somebody has touched it.
#:
#: Separate from priority on purpose: how bad a thing is and how far along the
#: answer to it is are different questions, and an alert that has been picked
#: up is still critical until it is fixed.
class AlertStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    IN_PROGRESS = "in_progress", "In Progress"
    RESOLVED = "resolved", "Resolved"
    DISMISSED = "dismissed", "Dismissed"


#: The statuses that still want somebody's attention. Everything the Action
#: Required widget shows is one of these; resolving or dismissing is precisely
#: what takes an alert off it.
OPEN_STATUSES = (AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED,
                 AlertStatus.IN_PROGRESS)

#: Status -> hex. Green appears here and nowhere else.
STATUS_COLOR = {
    AlertStatus.OPEN: "#64748b",
    AlertStatus.ACKNOWLEDGED: "#2563eb",
    AlertStatus.IN_PROGRESS: "#7c3aed",
    AlertStatus.RESOLVED: "#16a34a",
    AlertStatus.DISMISSED: "#64748b",
}

#: Priority -> the word the Action Required card puts on the badge.
#:
#: Not the same as ``Priority.label``, deliberately. The Alert Configuration
#: master is choosing an urgency level and "Medium" is the right word there;
#: the dashboard is telling somebody what kind of problem they are looking at,
#: and "Warning" and "Information" are what those two levels mean once they
#: are on a card. Renaming the choices themselves would change the master's
#: dropdowns to suit a widget, which is the wrong way round.
SEVERITY_LABEL = {
    Priority.CRITICAL: "Critical",
    Priority.HIGH: "High",
    Priority.MEDIUM: "Warning",
    Priority.LOW: "Information",
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
#:
#: Every name here must exist in the Font Awesome build base.html pins (6.0.0
#: free). A name that does not is not an error anywhere — the glyph is simply
#: blank, on the bell and the centre as well as the dashboard, and nobody
#: reports a missing picture. ``fa-wheat-awn`` was exactly that for Feed until
#: it was checked against the loaded stylesheet.
MODULE_ICON = {
    Module.PRODUCTION: "fa-solid fa-kiwi-bird",
    Module.FEED: "fa-solid fa-seedling",
    Module.HATCHERY: "fa-solid fa-egg",
    Module.HEALTH: "fa-solid fa-syringe",
    Module.INVENTORY: "fa-solid fa-boxes-stacked",
    Module.PURCHASE: "fa-solid fa-cart-shopping",
    Module.SALES: "fa-solid fa-file-invoice-dollar",
    Module.FINANCE: "fa-solid fa-indian-rupee-sign",
    Module.HR: "fa-solid fa-users",
    Module.SYSTEM: "fa-solid fa-server",
}


class Category(models.TextChoices):
    """What a hand-written notification is *about*, one level below Module.

    Module answers "which part of the business" and is what the automatic rules
    already carry. A person composing a message knows something narrower —
    "Mortality", "Vaccination" — and filing by it is what makes a month of sent
    messages searchable later.

    Deliberately a short, closed list. Free-text tags would drift into
    "mortality", "Mortality " and "high mortality" inside a week, and none of
    the three would find the others.
    """

    MORTALITY = "mortality", "Mortality"
    FEED = "feed", "Feed"
    MEDICINE = "medicine", "Medicine"
    VACCINATION = "vaccination", "Vaccination"
    WEIGHT = "weight", "Weight & FCR"
    STOCK = "stock", "Stock"
    DISPATCH = "dispatch", "Dispatch"
    PAYMENT = "payment", "Payment"
    APPROVAL = "approval", "Approval"
    ATTENDANCE = "attendance", "Attendance"
    MAINTENANCE = "maintenance", "Maintenance"
    ANNOUNCEMENT = "announcement", "Announcement"
    GENERAL = "general", "General"


#: Category -> Font Awesome icon, on the same principle as MODULE_ICON: one
#: place decides, so a category cannot look like two things on two screens.
CATEGORY_ICON = {
    Category.MORTALITY: "fa-solid fa-skull-crossbones",
    Category.FEED: "fa-solid fa-wheat-awn",
    Category.MEDICINE: "fa-solid fa-prescription-bottle-medical",
    Category.VACCINATION: "fa-solid fa-syringe",
    Category.WEIGHT: "fa-solid fa-weight-scale",
    Category.STOCK: "fa-solid fa-boxes-stacked",
    Category.DISPATCH: "fa-solid fa-truck-fast",
    Category.PAYMENT: "fa-solid fa-indian-rupee-sign",
    Category.APPROVAL: "fa-solid fa-circle-check",
    Category.ATTENDANCE: "fa-solid fa-user-clock",
    Category.MAINTENANCE: "fa-solid fa-screwdriver-wrench",
    Category.ANNOUNCEMENT: "fa-solid fa-bullhorn",
    Category.GENERAL: "fa-solid fa-circle-info",
}


class NotificationType(models.TextChoices):
    """What kind of message a person is composing.

    This is the one field the sender actually thinks in — "I am sending a
    mortality alert" — and Module and Category are both derivable from it (see
    :data:`TYPE_DEFAULTS`). Deriving them rather than asking three times is what
    keeps a "Mortality Alert" from being filed under Finance because a second
    dropdown was left on its default.

    Category stays editable afterwards, because the derivation is a sensible
    starting point and not a law: a Production Alert may legitimately be about
    weights rather than mortality.
    """

    GENERAL = "general", "General Notification"
    PRODUCTION = "production", "Production Alert"
    MORTALITY = "mortality", "Mortality Alert"
    FEED = "feed", "Feed Alert"
    MEDICINE = "medicine", "Medicine / Veterinary"
    VACCINATION = "vaccination", "Vaccination"
    HATCHERY = "hatchery", "Hatchery"
    INVENTORY = "inventory", "Inventory"
    PURCHASE = "purchase", "Purchase"
    SALES = "sales", "Sales / Dispatch"
    FINANCE = "finance", "Finance"
    HR = "hr", "HR"
    ATTENDANCE = "attendance", "Attendance"
    SYSTEM = "system", "System"


#: Notification type -> (module, suggested category). The page pre-selects the
#: category from here as the type changes; the sender may override it.
TYPE_DEFAULTS = {
    NotificationType.GENERAL: (Module.SYSTEM, Category.GENERAL),
    NotificationType.PRODUCTION: (Module.PRODUCTION, Category.GENERAL),
    NotificationType.MORTALITY: (Module.PRODUCTION, Category.MORTALITY),
    NotificationType.FEED: (Module.FEED, Category.FEED),
    NotificationType.MEDICINE: (Module.HEALTH, Category.MEDICINE),
    NotificationType.VACCINATION: (Module.HEALTH, Category.VACCINATION),
    NotificationType.HATCHERY: (Module.HATCHERY, Category.GENERAL),
    NotificationType.INVENTORY: (Module.INVENTORY, Category.STOCK),
    NotificationType.PURCHASE: (Module.PURCHASE, Category.APPROVAL),
    NotificationType.SALES: (Module.SALES, Category.DISPATCH),
    NotificationType.FINANCE: (Module.FINANCE, Category.PAYMENT),
    NotificationType.HR: (Module.HR, Category.GENERAL),
    NotificationType.ATTENDANCE: (Module.HR, Category.ATTENDANCE),
    NotificationType.SYSTEM: (Module.SYSTEM, Category.GENERAL),
}


def defaults_for_type(notification_type):
    """``(module, category)`` for a type, falling back to System/General."""
    return TYPE_DEFAULTS.get(
        notification_type, (Module.SYSTEM, Category.GENERAL)
    )


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
#: and had simply never been joined. SMS joined them the same way, through the
#: gateway the notification app has been sending on for months.
#:
#: SMS differs from the two above in one way worth stating here, where the
#: decision is visible: a push and a bell cost nothing, and an SMS costs money
#: per message. It is live, so a rule that asks for it is honoured — but the
#: asking is per rule, and the recipient can still refuse it.
LIVE_CHANNELS = frozenset({Channel.IN_APP, Channel.PUSH, Channel.SMS})


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
