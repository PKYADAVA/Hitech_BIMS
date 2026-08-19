"""URLs for the business-alert module.

Pages sit under ``/notifications/`` and the API under ``/api/alerthub/``, both
in the ``alerthub`` namespace. The API prefix is explicit rather than
``/api/notifications/`` because the ``notification`` app (SMS) already owns
that word in this project, and two similarly-named API roots is how someone
ends up polling the wrong one.
"""
from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import trigger, views
from .api import NotificationViewSet, PreferenceView

app_name = "alerthub"

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")
router.register("preferences", PreferenceView, basename="preference")

urlpatterns = [
    # Pages
    path("notifications/", views.notification_center, name="notification_center"),
    path("notifications/history/", views.notification_history,
         name="notification_history"),
    path("notifications/preferences/", views.preferences, name="preferences"),
    path("notifications/send/", views.send_notification,
         name="send_notification"),
    path("notifications/send/recipients/", views.send_notification_recipients,
         name="send_notification_recipients"),
    path("notifications/send/<int:pk>/edit/", views.send_notification,
         name="outgoing_edit"),
    path("notifications/send/<int:pk>/", views.outgoing_detail,
         name="outgoing_detail"),
    path("notifications/send/<int:pk>/cancel/", views.outgoing_cancel,
         name="outgoing_cancel"),
    path("notifications/<int:pk>/", views.notification_detail,
         name="notification_detail"),

    # Alert Configuration master
    path("alert-config/", views.alert_rule_list, name="alert_rule_list"),
    path("alert-config/new/", views.alert_rule_form, name="alert_rule_create"),
    path("alert-config/<int:pk>/", views.alert_rule_form, name="alert_rule_edit"),
    path("alert-config/<int:pk>/toggle/", views.alert_rule_toggle,
         name="alert_rule_toggle"),
    path("alert-config/<int:pk>/delete/", views.alert_rule_delete,
         name="alert_rule_delete"),
    path("alert-catalog/", views.alert_catalog, name="alert_catalog"),

    # The scan's way in from an outside scheduler. Not under /api/, which is
    # JWT territory for the phone; this is a machine with a shared secret and
    # no user behind it. See alerthub/trigger.py.
    path("tasks/alert-scan/", trigger.run_scan, name="run_alert_scan"),

    # API
    path("api/alerthub/", include(router.urls)),
]
