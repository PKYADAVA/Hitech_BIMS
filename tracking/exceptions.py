"""Exception hierarchy for the Employee Tracking subsystem.

Mirrors the notification app's taxonomy: adapters raise *typed* errors and
never retry internally — the sync service owns retry policy and converts
these into TrackingSync/TrackingLog rows, so business code never handles a
vendor failure directly.
"""


class TrackingError(Exception):
    """Base class for every tracking-related error."""


class TrackingConfigurationError(TrackingError):
    """Raised when a provider row is missing required configuration."""


class TrackingProviderError(TrackingError):
    """Raised when a provider rejects a request or returns an error.

    Attributes:
        error_code: Provider-specific error code, when available.
        transient: Whether the failure may succeed on retry.
        provider_response: Parsed provider payload for logging (sanitized —
            adapters must never place credentials in it).
    """

    def __init__(self, message, error_code=None, transient=False, provider_response=None):
        super().__init__(message)
        self.error_code = error_code
        self.transient = transient
        self.provider_response = provider_response


class TrackingTransientError(TrackingProviderError):
    """A provider/network failure that is safe to retry (timeouts, 5xx, 429)."""

    def __init__(self, message, error_code=None, provider_response=None):
        super().__init__(
            message, error_code=error_code, transient=True,
            provider_response=provider_response,
        )


class TrackingPermanentError(TrackingProviderError):
    """A provider failure that must not be retried (bad request, unknown entity)."""

    def __init__(self, message, error_code=None, provider_response=None):
        super().__init__(
            message, error_code=error_code, transient=False,
            provider_response=provider_response,
        )


class TrackingAuthError(TrackingPermanentError):
    """Credentials rejected — surfaced separately so the sync can flag the
    provider row as needing re-configuration instead of blindly retrying."""
