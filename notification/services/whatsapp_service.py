"""The single entry point business code uses to send WhatsApp messages.

``WhatsappService`` owns configuration resolution, provider selection,
template parameter resolution, retry policy, structured logging and error
containment. It never raises for a delivery failure: callers always receive
a :class:`~notification.dtos.WhatsappResult` so a WhatsApp problem can never
crash a request or background job. Mirrors
:class:`~notification.services.sms_service.SmsService` exactly; see that
module for the established shape.
"""

import logging

from ..conf import WhatsappConfig, load_whatsapp_config
from ..constants import WhatsappProviderName, WhatsappStatus
from ..dtos import WhatsappResult
from ..exceptions import (
    SmsValidationError,
    WhatsappError,
    WhatsappProviderError,
    WhatsappTransientError,
    WhatsappValidationError,
)
from ..providers.leminai import LeminaiProvider
from ..providers.whatsapp_base import WhatsappProvider
from ..providers.whatsapp_mock import MockWhatsappProvider
from ..retry import call_with_retry
from ..validators import mask_phone, normalize_phone

logger = logging.getLogger("notification.whatsapp")

# Provider registry. Extend this to add a different WhatsApp BSP without
# touching any caller: implement providers/<name>.py and register the class
# here, same convention as _PROVIDER_FACTORIES in sms_service.py.
_PROVIDER_FACTORIES = {
    WhatsappProviderName.LEMINAI: LeminaiProvider,
    WhatsappProviderName.MOCK: MockWhatsappProvider,
}


class WhatsappService:
    """Send WhatsApp template messages through the configured provider."""

    def __init__(self, config: WhatsappConfig = None, provider: WhatsappProvider = None):
        self._config = config or load_whatsapp_config()
        # Only a provider we built is ours to close; an injected one (tests)
        # stays the caller's.
        self._owns_provider = provider is None
        self._provider = provider or self._build_provider(self._config)

    def close(self) -> None:
        """Release the underlying provider's network resources, if we own it."""
        if self._owns_provider and self._provider is not None:
            self._provider.close()

    def __enter__(self) -> "WhatsappService":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @staticmethod
    def _build_provider(config: WhatsappConfig) -> WhatsappProvider:
        if config.mock:
            return MockWhatsappProvider()
        factory = _PROVIDER_FACTORIES.get(config.provider)
        if factory is None:
            logger.error("Unknown WhatsApp provider '%s'; falling back to mock.", config.provider)
            return MockWhatsappProvider()
        if factory is MockWhatsappProvider:
            return MockWhatsappProvider()
        return factory(config)

    def send_template(self, template_key, phone_number, context=None) -> WhatsappResult:
        """Resolve a :class:`~notification.models.WhatsappTemplate` by key
        against ``context`` and send it.

        ``context`` is a dict of ERP variable name -> value (the same shape
        callers already build for SMS templates / ``comm_sources.py`` rows).
        Template lookup/resolution errors are surfaced as an ``INVALID``
        result rather than an exception, matching the SMS service.
        """

        if not self._config.enabled:
            logger.info("WhatsApp disabled; skipping send to recipient=%s", mask_phone(phone_number))
            return WhatsappResult.failed(
                recipient=str(phone_number or ""),
                error="WhatsApp sending is disabled.",
                status=WhatsappStatus.DISABLED,
                provider=self._provider.name,
            )

        try:
            recipient = normalize_phone(phone_number, self._config.default_country_code)
        except SmsValidationError as exc:
            logger.warning(
                "WhatsApp validation failed recipient=%s reason=%s",
                mask_phone(phone_number), exc,
            )
            return WhatsappResult.failed(
                recipient=str(phone_number or ""),
                error=str(exc),
                status=WhatsappStatus.INVALID,
                provider=self._provider.name,
            )

        from .whatsapp_template_service import WhatsappTemplateService  # avoid circular import

        try:
            template_name, language, components = WhatsappTemplateService().resolve(
                template_key, context or {}
            )
        except WhatsappValidationError as exc:
            logger.warning("WhatsApp template error key=%s reason=%s", template_key, exc)
            return WhatsappResult.failed(
                recipient=recipient,
                error=str(exc),
                status=WhatsappStatus.INVALID,
                provider=self._provider.name,
            )

        return self._dispatch(recipient, template_name, language, components)

    def _dispatch(self, recipient, template_name, language, components) -> WhatsappResult:
        try:
            return call_with_retry(
                lambda: self._provider.send_template(recipient, template_name, language, components),
                max_retries=self._config.max_retries,
                backoff=self._config.retry_backoff,
                transient_exception=WhatsappTransientError,
            )
        except WhatsappProviderError as exc:
            logger.error(
                "WhatsApp send failed recipient=%s provider=%s code=%s transient=%s error=%s",
                mask_phone(recipient), self._provider.name,
                exc.error_code, exc.transient, exc,
            )
            return WhatsappResult.failed(
                recipient=recipient,
                error=str(exc),
                error_code=exc.error_code,
                provider=self._provider.name,
                provider_response=exc.provider_response,
            )
        except WhatsappError as exc:
            logger.error(
                "WhatsApp send failed recipient=%s provider=%s error=%s",
                mask_phone(recipient), self._provider.name, exc,
            )
            return WhatsappResult.failed(
                recipient=recipient, error=str(exc), provider=self._provider.name,
            )
        except Exception as exc:  # pylint: disable=broad-except
            # Last-resort guard: a WhatsApp failure must never crash the caller.
            logger.exception(
                "Unexpected WhatsApp error recipient=%s provider=%s",
                mask_phone(recipient), self._provider.name,
            )
            return WhatsappResult.failed(
                recipient=recipient,
                error=f"Unexpected error: {exc}",
                provider=self._provider.name,
            )


_default_service = None  # pylint: disable=invalid-name
_settings_stamp = None  # pylint: disable=invalid-name


def _current_settings_stamp():
    """Version marker for the WhatsappSettings master row (its ``modified_at``).

    A change in the stamp means the shared service must be rebuilt so edits
    made in the WhatsApp Settings page apply immediately, without a restart
    and in every worker process.
    """

    try:
        from ..models import WhatsappSettings  # local import: avoid circulars at load time

        return (WhatsappSettings.objects.filter(pk=1)
                .values_list("modified_at", flat=True).first())
    except Exception:  # pylint: disable=broad-except
        return None


def get_whatsapp_service() -> WhatsappService:
    """Return a shared :class:`WhatsappService`, rebuilt when WhatsApp
    Settings change.

    Convenient for view/signal code that just wants
    ``get_whatsapp_service().send_template(...)``. Construct
    :class:`WhatsappService` directly when you need custom config/provider
    (e.g. in tests).
    """

    global _default_service, _settings_stamp  # pylint: disable=global-statement
    stamp = _current_settings_stamp()
    if _default_service is None or stamp != _settings_stamp:
        # Close the outgoing service's HTTP session before replacing it, so a
        # settings change doesn't abandon a live connection pool in the worker.
        if _default_service is not None:
            _default_service.close()
        _default_service = WhatsappService()
        _settings_stamp = stamp
    return _default_service
