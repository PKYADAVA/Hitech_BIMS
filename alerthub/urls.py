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

from . import views
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
    path("notifications/<int:pk>/", views.notification_detail,
         name="notification_detail"),

    # Alert Configuration master
    path("alert-config/", views.alert_rule_list, name="alert_rule_list"),
    path("alert-config/new/", views.alert_rule_form, name="alert_rule_create"),
    path("alert-config/<int:pk>/", views.alert_rule_form, name="alert_rule_edit"),
    path("alert-config/<int:pk>/delete/", views.alert_rule_delete,
         name="alert_rule_delete"),
    path("alert-catalog/", views.alert_catalog, name="alert_catalog"),

    # API
    path("api/alerthub/", include(router.urls)),
]
