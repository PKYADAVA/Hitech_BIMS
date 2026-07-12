"""Business-facing SMS services.

Import ``get_sms_service`` (or ``SmsService``) here and call ``send_sms`` or
``send_template``; the provider, retries, validation and logging are handled
internally.
"""

from .sms_service import SmsService, get_sms_service
from .template_service import SmsTemplateService

__all__ = ["SmsService", "get_sms_service", "SmsTemplateService"]
