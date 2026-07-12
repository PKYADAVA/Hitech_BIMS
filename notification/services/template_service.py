"""Resolve and render SMS templates.

Resolution order for a template key:
  1. An active :class:`~notification.models.SmsTemplate` row (admin-editable).
  2. The built-in catalogue default (:mod:`notification.templates_catalog`).

Rendering validates that every ``{placeholder}`` in the body is supplied, so a
missing merge field is reported clearly instead of producing a broken message.
"""

import logging
from collections import namedtuple
from string import Formatter

from django.db import Error as DatabaseError

from ..exceptions import SmsValidationError
from ..templates_catalog import DEFAULT_TEMPLATES_BY_KEY

logger = logging.getLogger("notification.sms")

#: A resolved template's renderable body plus its optional DLT template ID.
ResolvedTemplate = namedtuple("ResolvedTemplate", ("body", "dlt_template_id"))


def extract_placeholders(body):
    """Return the set of named ``{placeholder}`` fields used in ``body``."""

    names = set()
    for _, field_name, _, _ in Formatter().parse(body or ""):
        if field_name:
            # Support dotted/indexed access by keying on the root name.
            names.add(field_name.split(".")[0].split("[")[0])
    return names


class SmsTemplateService:
    """Look up and render configurable SMS templates."""

    def resolve(self, key):
        """Return the :class:`ResolvedTemplate` for ``key`` (DB override → catalogue).

        Raises:
            SmsValidationError: if the key is unknown.
        """

        row = self._db_row(key)
        if row is not None:
            return ResolvedTemplate(row[0], row[1] or "")

        default = DEFAULT_TEMPLATES_BY_KEY.get(key)
        if default is None:
            raise SmsValidationError(f"Unknown SMS template '{key}'.")
        return ResolvedTemplate(default.body, default.dlt_template_id)

    def get_body(self, key):
        """Return the active template body for ``key``."""

        return self.resolve(key).body

    def render(self, key, context):
        """Render template ``key`` with ``context`` and return the message text."""

        return self.render_with_dlt(key, context)[0]

    def render_with_dlt(self, key, context):
        """Return ``(message, dlt_template_id)`` for ``key`` rendered with ``context``.

        Raises:
            SmsValidationError: for an unknown key or missing placeholders.
        """

        resolved = self.resolve(key)
        required = extract_placeholders(resolved.body)
        missing = sorted(name for name in required if name not in (context or {}))
        if missing:
            raise SmsValidationError(
                f"Missing placeholders for template '{key}': {', '.join(missing)}."
            )
        try:
            message = resolved.body.format(**context)
        except (KeyError, IndexError, ValueError) as exc:
            raise SmsValidationError(
                f"Failed to render template '{key}': {exc}."
            ) from exc
        return message, resolved.dlt_template_id

    @staticmethod
    def _db_row(key):
        """Return the active DB row's ``(body, dlt_template_id)``, or ``None``.

        Defends against the table not existing yet (e.g. before migrations run)
        by falling back to the catalogue rather than raising.
        """

        # Imported here so importing this module never requires the app registry
        # to be ready (keeps it safe to import from settings-adjacent code).
        from ..models import SmsTemplate  # pylint: disable=import-outside-toplevel

        try:
            return (
                SmsTemplate.objects
                .filter(key=key, is_active=True)
                .values_list("body", "dlt_template_id")
                .first()
            )
        except DatabaseError:
            logger.debug("SmsTemplate table unavailable; using catalogue for key=%s", key)
            return None
