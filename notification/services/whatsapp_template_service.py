"""Resolve a WhatsApp template record into a sendable payload.

Unlike SMS there is no built-in catalogue fallback: a WhatsApp template only
exists once it has been approved by Meta and registered here with its exact
``template_name``/``language``, so resolution is DB-only. Mirrors
:mod:`~notification.services.template_service`'s shape.
"""

import logging
from collections import namedtuple

from django.db import Error as DatabaseError

from ..exceptions import WhatsappValidationError

logger = logging.getLogger("notification.whatsapp")

#: A resolved template's send-ready pieces.
ResolvedWhatsappTemplate = namedtuple(
    "ResolvedWhatsappTemplate", ("template_name", "language", "components")
)


class WhatsappTemplateService:
    """Look up a configurable WhatsApp template and build its Meta components."""

    def resolve(self, key, context):
        """Return ``(template_name, language, components)`` for ``key``,
        with ``context`` values filled into the template's parameter
        positions.

        Raises:
            WhatsappValidationError: for an unknown/inactive key or a
                parameter position with no matching value in ``context``.
        """

        row = self._db_row(key)
        if row is None:
            raise WhatsappValidationError(f"Unknown WhatsApp template '{key}'.")

        template_name, language, parameter_map, header_type, header_media_url = row
        context = context or {}

        missing = [name for name in (parameter_map or []) if name not in context]
        if missing:
            raise WhatsappValidationError(
                f"Missing parameters for WhatsApp template '{key}': {', '.join(missing)}."
            )

        components = []
        if header_type in ("image", "video", "document") and header_media_url:
            components.append({
                "type": "header",
                "parameters": [{
                    "type": header_type,
                    header_type: {"link": header_media_url},
                }],
            })
        if parameter_map:
            components.append({
                "type": "body",
                "parameters": [
                    {"type": "text", "text": str(context[name])} for name in parameter_map
                ],
            })
        return ResolvedWhatsappTemplate(template_name, language, components)

    @staticmethod
    def _db_row(key):
        """Return the active DB row's send-relevant fields, or ``None``.

        Defends against the table not existing yet (e.g. before migrations
        run) by returning ``None`` rather than raising.
        """

        # Imported here so importing this module never requires the app
        # registry to be ready, matching template_service.py's convention.
        from ..models import WhatsappTemplate  # pylint: disable=import-outside-toplevel

        try:
            return (
                WhatsappTemplate.objects
                .filter(key=key, is_active=True)
                .values_list("template_name", "language", "parameter_map",
                            "header_type", "header_media_url")
                .first()
            )
        except DatabaseError:
            logger.debug("WhatsappTemplate table unavailable; key=%s", key)
            return None
