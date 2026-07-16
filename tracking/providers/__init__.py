"""Provider registry: maps a ``TrackingProvider.provider_type`` to its adapter.

Adding a GPS vendor = write one adapter module implementing
:class:`~tracking.providers.base.TrackingProviderAdapter` and register it
here. Nothing above this package changes.
"""

from ..exceptions import TrackingConfigurationError
from .base import TrackingProviderAdapter
from .mock import MockProviderAdapter
from .trackwick import TrackWickProviderAdapter

#: provider_type (TrackingProvider.PROVIDER_CHOICES) -> adapter class.
#: "trackolap" is the TrackWick platform's pre-rebrand name; both map to the
#: same adapter so existing rows keep working whichever name was chosen.
ADAPTERS = {
    "trackolap": TrackWickProviderAdapter,
    "mock": MockProviderAdapter,
}


def get_adapter(provider) -> TrackingProviderAdapter:
    """Return a ready-to-use adapter for a ``TrackingProvider`` row.

    Raises :class:`TrackingConfigurationError` for provider types that have
    no adapter yet (geopunch/traccar/custom are registry slots awaiting an
    implementation — configuring one is a setup mistake, not a crash).
    """
    adapter_class = ADAPTERS.get(provider.provider_type)
    if adapter_class is None:
        raise TrackingConfigurationError(
            f"No adapter implemented for provider type '{provider.provider_type}'. "
            f"Available: {', '.join(sorted(ADAPTERS))}."
        )
    return adapter_class(provider)
