"""The single entry point business code uses to send SMS.

``SmsService`` owns configuration resolution, provider selection, validation,
retry policy, structured logging and error containment. It never raises for a
delivery failure: callers always receive a :class:`~notification.dtos.SmsResult`
so an SMS problem can never crash a request or background job.
"""

import logging

from ..conf import SmsConfig, load_config
from ..constants import SmsProviderName, SmsStatus
from ..dtos import SmsResult
from ..exceptions import SmsError, SmsProviderError, SmsValidationError
from ..providers.base import SmsProvider
from ..providers.mock import MockSmsProvider
from ..providers.smsgatewayhub import SmsGatewayHubProvider
from ..retry import call_with_retry
from ..validators import mask_phone, normalize_phone, validate_message

logger = logging.getLogger("notification.sms")

# Provider registry. Extend this to add MSG91/Twilio/AWS SNS without touching
# any caller: implement providers/<name>.py and register the class here.
_PROVIDER_FACTORIES = {
    SmsProviderName.SMSGATEWAYHUB: SmsGatewayHubProvider,
    SmsProviderName.MOCK: MockSmsProvider,
}


class SmsService:
    """Send SMS messages through the configured provider."""

    def __init__(self, config: SmsConfig = None, provider: SmsProvider = None):
        self._config = config or load_config()
        self._provider = provider or self._build_provider(self._config)

    @staticmethod
    def _build_provider(config: SmsConfig) -> SmsProvider:
        if config.mock:
            return MockSmsProvider()
        factory = _PROVIDER_FACTORIES.get(config.provider)
        if factory is None:
            logger.error("Unknown SMS provider '%s'; falling back to mock.", config.provider)
            return MockSmsProvider()
        if factory is MockSmsProvider:
            return MockSmsProvider()
        return factory(config)

    def send_sms(self, phone_number, message, options=None) -> SmsResult:
        """Validate and send a single SMS, returning a structured result.

        ``options`` carries optional provider routing hints (e.g.
        ``{"dlt_template_id": "..."}``) and is passed straight to the provider.
        """

        if not self._config.enabled:
            logger.info("SMS disabled; skipping send to recipient=%s", mask_phone(phone_number))
            return SmsResult.failed(
                recipient=str(phone_number or ""),
                error="SMS sending is disabled.",
                status=SmsStatus.DISABLED,
                provider=self._provider.name,
            )

        try:
            recipient = normalize_phone(phone_number, self._config.default_country_code)
            text = validate_message(message, self._config.max_length)
        except SmsValidationError as exc:
            logger.warning(
                "SMS validation failed recipient=%s reason=%s",
                mask_phone(phone_number), exc,
            )
            return SmsResult.failed(
                recipient=str(phone_number or ""),
                error=str(exc),
                status=SmsStatus.INVALID,
                provider=self._provider.name,
            )

        return self._dispatch(recipient, text, options or {})

    def send_template(self, template_key, phone_number, context=None) -> SmsResult:
        """Render an editable template by key and send it.

        Template lookup/rendering errors are surfaced as an ``INVALID`` result
        rather than an exception, matching :meth:`send_sms`.
        """

        # Imported lazily to avoid a circular import at module load time.
        from .template_service import SmsTemplateService  # pylint: disable=import-outside-toplevel

        try:
            message, dlt_template_id = SmsTemplateService().render_with_dlt(
                template_key, context or {}
            )
        except SmsValidationError as exc:
            logger.warning("SMS template error key=%s reason=%s", template_key, exc)
            return SmsResult.failed(
                recipient=str(phone_number or ""),
                error=str(exc),
                status=SmsStatus.INVALID,
                provider=self._provider.name,
            )
        options = {"dlt_template_id": dlt_template_id} if dlt_template_id else None
        return self.send_sms(phone_number, message, options=options)

    def _dispatch(self, recipient, text, options) -> SmsResult:
        try:
            return call_with_retry(
                lambda: self._provider.send(recipient, text, options),
                max_retries=self._config.max_retries,
                backoff=self._config.retry_backoff,
            )
        except SmsProviderError as exc:
            logger.error(
                "SMS send failed recipient=%s provider=%s code=%s transient=%s error=%s",
                mask_phone(recipient), self._provider.name,
                exc.error_code, exc.transient, exc,
            )
            return SmsResult.failed(
                recipient=recipient,
                error=str(exc),
                error_code=exc.error_code,
                provider=self._provider.name,
                provider_response=exc.provider_response,
            )
        except SmsError as exc:
            logger.error(
                "SMS send failed recipient=%s provider=%s error=%s",
                mask_phone(recipient), self._provider.name, exc,
            )
            return SmsResult.failed(
                recipient=recipient, error=str(exc), provider=self._provider.name,
            )
        except Exception as exc:  # pylint: disable=broad-except
            # Last-resort guard: an SMS failure must never crash the caller.
            logger.exception(
                "Unexpected SMS error recipient=%s provider=%s",
                mask_phone(recipient), self._provider.name,
            )
            return SmsResult.failed(
                recipient=recipient,
                error=f"Unexpected error: {exc}",
                provider=self._provider.name,
            )


_default_service = None  # pylint: disable=invalid-name
_settings_stamp = None  # pylint: disable=invalid-name


def _current_settings_stamp():
    """Version marker for the SmsSettings master row (its ``modified_at``).

    A change in the stamp means the shared service must be rebuilt so edits
    made in the SMS Settings page apply immediately, without a restart and in
    every worker process.
    """

    try:
        from ..models import SmsSettings  # local import: avoid circulars at load time

        return (SmsSettings.objects.filter(pk=1)
                .values_list("modified_at", flat=True).first())
    except Exception:  # pylint: disable=broad-except
        return None


def get_sms_service() -> SmsService:
    """Return a shared :class:`SmsService`, rebuilt when SMS Settings change.

    Convenient for view/signal code that just wants ``get_sms_service().send_sms(...)``.
    Construct :class:`SmsService` directly when you need custom config/provider
    (e.g. in tests).
    """

    global _default_service, _settings_stamp  # pylint: disable=global-statement
    stamp = _current_settings_stamp()
    if _default_service is None or stamp != _settings_stamp:
        _default_service = SmsService()
        _settings_stamp = stamp
    return _default_service
