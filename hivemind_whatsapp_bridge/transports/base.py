"""Transport interface shared by every WhatsApp integration path."""
from abc import ABC, abstractmethod
from typing import Callable, Optional

# handler(sender_id: str, text: str) -> None
MessageHandler = Callable[[str, str], None]


class WhatsAppTransport(ABC):
    """A WhatsApp integration path.

    ``HiveMindWhatsappBridge`` only ever talks to this interface, never
    to a specific transport's internals. That is what makes the
    ``cloud`` and ``personal`` paths interchangeable behind
    ``--transport``.

    Lifecycle contract:

    - :meth:`set_message_handler` is called once, before
      :meth:`start`, to register the callback that hands inbound
      ``(sender, text)`` pairs to the bridge.
    - :meth:`start` must be **non-blocking**: set up whatever server,
      socket or background thread the transport needs and return. The
      caller (``__main__``) decides how to block the process afterwards
      (e.g. run a webhook server, or just wait on a stop event).
    - The transport must not call the message handler for anything
      that arrives before :meth:`start` has set things up, and it is
      the bridge's job -- not the transport's -- to decide whether a
      HiveMind connection is up yet before acting on a message.
    - :meth:`stop` releases whatever :meth:`start` acquired. Idempotent.
    """

    def __init__(self) -> None:
        self._on_message: Optional[MessageHandler] = None

    def set_message_handler(self, handler: MessageHandler) -> None:
        """Register the callback invoked for every inbound text message.

        ``handler(sender, text)`` where ``sender`` is a transport-specific
        but stable identifier for the chat to reply to later (a phone
        number for both transports here).
        """
        self._on_message = handler

    @abstractmethod
    def start(self) -> None:
        """Start receiving messages. Must return without blocking."""

    @abstractmethod
    def stop(self) -> None:
        """Stop receiving messages and release resources. Idempotent."""

    @abstractmethod
    def send(self, recipient: str, text: str) -> None:
        """Send ``text`` to ``recipient`` (as identified by ``sender`` above)."""


__all__ = ["WhatsAppTransport", "MessageHandler"]
