"""Exception hierarchy for the SMS notification subsystem.

The service layer catches these internally and converts them into structured
results, so business code never has to handle provider failures directly.
"""


class SmsError(Exception):
    """Base class for every SMS-related error."""


class SmsConfigurationError(SmsError):
    """Raised when required SMS settings are missing or invalid."""


class SmsValidationError(SmsError):
    """Raised when a phone number or message fails validation."""


class SmsProviderError(SmsError):
    """Raised when a provider rejects a request or returns an error.

    Attributes:
        error_code: Provider-specific error code, when available.
        transient: Whether the failure may succeed on retry.
        provider_response: Parsed provider payload, for logging/diagnostics.
    """

    def __init__(self, message, error_code=None, transient=False, provider_response=None):
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient
        self.provider_response = provider_response


class SmsTransientError(SmsProviderError):
    """A provider/network failure that is safe to retry."""

    def __init__(self, message, error_code=None, provider_response=None):
        super().__init__(
            message,
            error_code=error_code,
            transient=True,
            provider_response=provider_response,
        )


class SmsPermanentError(SmsProviderError):
    """A provider failure that must not be retried (e.g. invalid credentials)."""

    def __init__(self, message, error_code=None, provider_response=None):
        super().__init__(
            message,
            error_code=error_code,
            transient=False,
            provider_response=provider_response,
        )
