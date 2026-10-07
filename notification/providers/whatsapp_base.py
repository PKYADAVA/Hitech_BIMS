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

    def close(self) -> None:
        """Release any network resources (HTTP session/sockets) held.

        Default no-op. Providers that open a ``requests.Session`` override
        this so a rebuilt/discarded provider doesn't leak its connection pool.
        """

    def __enter__(self) -> "WhatsappProvider":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
