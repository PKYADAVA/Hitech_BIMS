"""URL routes for the notification (SMS) in-app UI."""

from django.urls import path

from .views import (
    SmsTemplateAPI,
    SmsTemplateManageView,
    send_sms_template,
    toggle_sms_template_active,
)

urlpatterns = [
    path("sms-templates/", SmsTemplateManageView.as_view(), name="sms_templates"),
    path("sms-templates/list/", SmsTemplateAPI.as_view(), name="sms_template_list"),
    path("sms-templates/create/", SmsTemplateAPI.as_view(), name="sms_template_create"),
    path("sms-templates/<int:template_id>/", SmsTemplateAPI.as_view(),
         name="sms_template_edit"),
    path("sms-templates/<int:template_id>/delete/", SmsTemplateAPI.as_view(),
         name="sms_template_delete"),
    path("sms-templates/<int:template_id>/toggle-active/", toggle_sms_template_active,
         name="sms_template_toggle_active"),
    path("sms-templates/<int:template_id>/send/", send_sms_template,
         name="sms_template_send"),
]
