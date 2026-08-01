"""Storage indirection for model file fields.

Public media (photos, operational images) uses Django's default storage.
Sensitive documents (KYC scans, cheques, agreements, reference copies) use the
``private_media`` storage: on DigitalOcean Spaces that is a private bucket area
served through short-lived signed URLs (see settings.STORAGES); in local
development it falls back to the filesystem.

``FileField(storage=...)`` is given the *callable* below rather than a storage
instance so the configured backend is resolved lazily at runtime and stays
consistent whether or not Spaces is enabled. A module-level function also keeps
migrations stable — they record this import path, not an environment-specific
storage object.
"""

from django.core.files.storage import storages


def private_media_storage():
    """Return the configured ``private_media`` backend."""
    return storages["private_media"]
