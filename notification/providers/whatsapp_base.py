"""Provider interface that decouples WhatsApp business logic from any gateway."""

from abc import ABC, abstractmethod

from ..dtos import WhatsappResult


class WhatsappProvider(ABC):
    """Contract every WhatsApp gateway implementation must satisfy."""

    #: Short, stable identifier recorded on results and in logs.
    name = "base"

    @abstractmethod
    def send_template(self, phone: str, template_name: str, language: str,
                      components: list) -> WhatsappResult:
        """Send one approved template to one already-normalised MSISDN.

        ``components`` follows the Meta Graph API shape (a list of
        ``{"type": "header"|"body"|"button", ...}`` objects) exactly as the
        gateway's wire format expects — the service layer builds this from a
        :class:`~notification.models.WhatsappTemplate`'s ``parameter_map``,
        so providers never need to know about ERP template records.

        Implementations must not retry internally; the service layer owns
        retry policy. They should raise
        :class:`~notification.exceptions.WhatsappTransientError` for
        retryable failures and
        :class:`~notification.exceptions.WhatsappPermanentError` otherwise.
        """

    def get_status(self, provider_message_id: str):
        """Return ``(status, raw_response)`` for a previously sent message,
        or ``None`` if the check cannot be completed (no support, network
        failure, bad id).

        ``provider_message_id`` is the gateway's own id for the send, not
        necessarily the WAMID — see the concrete provider for which one it
        expects. Default: unsupported. Providers that can answer this
        override it.
        """
        return None

    def send_text(self, phone: str, body: str) -> WhatsappResult:
        """Send a free-form (session) text message to an already-normalised
        MSISDN. Only valid inside the contact's 24-hour service window —
        implementations raise :class:`~notification.exceptions.WhatsappPermanentError`
        (not transient — waiting doesn't fix it) when outside it.

        Default: unsupported (raises). Providers that can send a service
        message override it.
        """
        raise NotImplementedError(f"{self.name} does not support free-text service messages.")

    def get_conversation(self, phone: str, per_page: int = 50, page: int = 1, order: str = "asc"):
        """Return ``(messages, meta)`` for the thread with ``phone``, or
        ``None`` if the call cannot be completed.

        Default: unsupported. Providers that can answer this override it.
        """
        return None

    def create_contact(self, name: str, phone: str, custom_fields=None, groups=None):
        """Return ``(success, data_or_error)`` for creating a contact.

        Default: unsupported — returns a failure tuple rather than raising,
        since contact sync is an auxiliary action. Providers that can
        create contacts override it.
        """
        return False, f"{self.name} does not support contact creation."

    def get_groups(self):
        """Return the list of contact groups for this account, or ``None``
        if unsupported/unavailable. Default: unsupported."""
        return None

    def get_media_link(self, media_id: str):
        """Return a temporary download URL dict for ``media_id``, or
        ``None`` if unsupported/unavailable. Default: unsupported."""
        return None

    def lookup_contact(self, phone: str):
        """Return ``True``/``False``/``None`` for whether ``phone`` is a
        known contact on this channel.

        This is NOT a genuine "is this number on WhatsApp" check — no such
        check exists in the LemIn AI API this provider wraps. It only
        answers "has this number been seen before" (saved as a contact).
        ``None`` means the provider cannot answer (no lookup support, or the
        check itself failed) and callers should treat that as "unknown",
        never as a reason to block a send.

        Default: unsupported. Providers that can answer this override it.
        """
        return None

    def close(self) -> None:
        """Release any network resources (HTTP session/sockets) held.

        Default no-op. Providers that open a ``requests.Session`` override
        this so a rebuilt/discarded provider doesn't leak its connection pool.
        """

    def __enter__(self) -> "WhatsappProvider":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
