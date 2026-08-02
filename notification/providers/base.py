"""Provider interface that decouples business logic from any gateway."""

from abc import ABC, abstractmethod

from ..dtos import SmsResult


class SmsProvider(ABC):
    """Contract every SMS gateway implementation must satisfy."""

    #: Short, stable identifier recorded on results and in logs.
    name = "base"

    @abstractmethod
    def send(self, phone: str, message: str, options: dict = None) -> SmsResult:
        """Send one message to one already-normalised MSISDN.

        ``options`` is an optional bag of provider-agnostic routing hints (e.g.
        ``{"dlt_template_id": "..."}``). Providers use the keys they understand
        and ignore the rest, so business code stays free of provider specifics.

        Implementations must not retry internally; the service layer owns retry
        policy. They should raise :class:`~notification.exceptions.SmsTransientError`
        for retryable failures and
        :class:`~notification.exceptions.SmsPermanentError` otherwise.
        """

    def close(self) -> None:
        """Release any network resources (HTTP session/sockets) held.

        Default no-op. Providers that open a ``requests.Session`` override this
        so a rebuilt/discarded provider doesn't leak its connection pool.
        """

    def __enter__(self) -> "SmsProvider":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
