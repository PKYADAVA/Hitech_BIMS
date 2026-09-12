"""Project-wide template context.

`company` is needed by the shared report letterhead on every report page, so it
is injected here rather than added to each report view's context by hand. The
singleton is cached because it is read on every request and effectively never
changes.

`map_tiles` is here for the opposite reason: it is needed by only a handful of
pages, but it was copied into every one of them, so when OpenStreetMap blocked
the tile server there were eight places to change instead of one.
"""

from django.core.cache import cache

_CACHE_KEY = "company_profile_solo"
_CACHE_TTL = 300  # seconds


def company(request):
    """The CompanyProfile singleton, for letterheads and printed documents."""
    profile = cache.get(_CACHE_KEY)
    if profile is None:
        from account.models import CompanyProfile
        profile = CompanyProfile.get_solo()
        cache.set(_CACHE_KEY, profile, _CACHE_TTL)
    return {"company": profile}


def map_tiles(request):
    """Where the maps get their tiles, and who has to be credited for them.

    Read from settings on every request rather than cached: it changes about
    once a year, and a cache would only add a way for a provider switch to
    half-apply.
    """
    from django.conf import settings

    return {"MAP_TILES": {"url": settings.MAP_TILE_URL,
                          "attribution": settings.MAP_TILE_ATTRIBUTION,
                          "maxZoom": settings.MAP_TILE_MAX_ZOOM}}
