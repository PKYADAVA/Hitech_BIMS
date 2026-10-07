"""URL routes for the notification (SMS) in-app UI."""

from django.urls import path

from .views import (
    SmsTemplateAPI,
    SmsTemplateManageView,
    SmsTransactionPageView,
    SmsHistoryPageView,
    SmsSettingsPageView,
    WhatsappSettingsPageView,
    WhatsappTemplateAPI,
    WhatsappTemplateManageView,
    WhatsappTransactionPageView,
    sms_settings_test,
    send_sms_template,
    send_whatsapp_template,
    sms_history,
    sms_retry,
    sms_send,
    sms_transaction_source,
    toggle_sms_template_active,
    toggle_whatsapp_template_active,
    whatsapp_settings_test,
    whatsapp_transaction_source,
    whatsapp_transaction_send,
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

    path("sms-transaction/", SmsTransactionPageView.as_view(), name="sms_transaction"),
    path("sms-transaction/source/", sms_transaction_source, name="sms_transaction_source"),
    path("sms-transaction/send/", sms_send, name="sms_transaction_send"),
    path("sms-history/", SmsHistoryPageView.as_view(), name="sms_history"),
    path("sms-history/list/", sms_history, name="sms_history_api"),
    path("sms-history/<int:message_id>/retry/", sms_retry, name="sms_history_retry"),

    path("sms-settings/", SmsSettingsPageView.as_view(), name="sms_settings"),
    path("sms-settings/test/", sms_settings_test, name="sms_settings_test"),

    path("whatsapp-templates/", WhatsappTemplateManageView.as_view(), name="whatsapp_templates"),
    path("whatsapp-templates/list/", WhatsappTemplateAPI.as_view(), name="whatsapp_template_list"),
    path("whatsapp-templates/create/", WhatsappTemplateAPI.as_view(), name="whatsapp_template_create"),
    path("whatsapp-templates/<int:template_id>/", WhatsappTemplateAPI.as_view(),
         name="whatsapp_template_edit"),
    path("whatsapp-templates/<int:template_id>/delete/", WhatsappTemplateAPI.as_view(),
         name="whatsapp_template_delete"),
    path("whatsapp-templates/<int:template_id>/toggle-active/", toggle_whatsapp_template_active,
         name="whatsapp_template_toggle_active"),
    path("whatsapp-templates/<int:template_id>/send/", send_whatsapp_template,
         name="whatsapp_template_send"),

    path("whatsapp-settings/", WhatsappSettingsPageView.as_view(), name="whatsapp_settings"),
    path("whatsapp-settings/test/", whatsapp_settings_test, name="whatsapp_settings_test"),

    path("whatsapp-transaction/", WhatsappTransactionPageView.as_view(), name="whatsapp_transaction"),
    path("whatsapp-transaction/source/", whatsapp_transaction_source, name="whatsapp_transaction_source"),
    path("whatsapp-transaction/send/", whatsapp_transaction_send, name="whatsapp_transaction_send"),
]
