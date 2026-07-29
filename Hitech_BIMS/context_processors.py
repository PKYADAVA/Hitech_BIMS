"""Project-wide template context.

`company` is needed by the shared report letterhead on every report page, so it
is injected here rather than added to each report view's context by hand. The
singleton is cached because it is read on every request and effectively never
changes.
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
