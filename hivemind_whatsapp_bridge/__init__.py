"""HiveMind <-> WhatsApp bridge.

A HiveMind bridge is a satellite whose input and output are a chat
platform instead of a microphone. This bridge supports two interchangeable
WhatsApp *transports*, selected at deploy time (see ``--transport`` in
``__main__``):

- ``cloud`` (default): Meta's official **WhatsApp Business Cloud API**.
  Webhook in, REST out. The only officially supported, ToS-safe path.
- ``personal``: pairs to a personal WhatsApp number via the
  reverse-engineered multi-device protocol (``neonize``/``whatsmeow``).
  Unofficial, against WhatsApp's Terms of Service, and can get the
  paired number banned. See
  ``hivemind_whatsapp_bridge.transports.personal`` and the README before
  using it.

Everything below this line is transport-agnostic: it only talks to a
``WhatsAppTransport`` (``hivemind_whatsapp_bridge.transports.base``), so
the same HiveMind lifecycle and routing logic works for either.

Connection lifecycle, spelled out because getting it wrong is the
recurring bug across every HiveMind bridge written so far:

- ``HiveMessageBusClient.connect()`` already starts and owns the
  reconnect worker in a background thread, and blocks synchronously
  until the handshake completes (or fails). Call it exactly once. Do
  not also call ``run_forever()`` afterwards -- there is nothing left
  to start, the connection is already live in its own thread.
- Nothing is forwarded to HiveMind before ``connect_hivemind()`` returns.
- host/port are configuration, not constants.
- a freshly registered HiveMind client is denied every message type
  until a hub admin runs ``hivemind-core allow-msg
  recognizer_loop:utterance <client_id>`` (and usually ``speak`` too);
  this bridge cannot do that step itself. See the README.
"""
from typing import Optional

from hivemind_bus_client import (
    HiveMessage,
    HiveMessageType,
    HiveMessageBusClient,
)
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from hivemind_whatsapp_bridge.transports import WhatsAppTransport

platform = "HiveMindWhatsappBridgeV0.2"


class HiveMindWhatsappBridge:
    """Bridge a ``WhatsAppTransport`` to a HiveMind node."""

    def __init__(self,
                 transport: WhatsAppTransport,
                 key: Optional[str] = None,
                 password: Optional[str] = None,
                 host: Optional[str] = None,
                 port: int = 5678,
                 self_signed: bool = False,
                 lang: str = "en-us",
                 site_id: str = "whatsapp",
                 *,
                 client: Optional[HiveMessageBusClient] = None):
        """
        Parameters
        ----------
        transport: the WhatsApp integration path (cloud or personal),
            already constructed with its own credentials/session.
        key, password, host, port, self_signed: HiveMind hub connection.
        lang: default utterance language tag.
        site_id: this bridge's HiveMind site id.
        client: pre-built HiveMessageBusClient (tests / advanced setups).
        """
        self.transport = transport
        self.transport.set_message_handler(self._on_whatsapp_message)

        self.lang = lang
        self.site_id = site_id

        self.client = client or HiveMessageBusClient(
            key=key,
            password=password,
            host=host,
            port=port,
            useragent=platform,
            self_signed=self_signed,
        )
        self._connected = False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def connect_hivemind(self) -> None:
        """Connect to the HiveMind hub and wait for the handshake.

        Calls ``HiveMessageBusClient.connect()`` exactly once; that call
        already starts and owns the reconnect worker thread. Never call
        ``run_forever()`` in addition to this.
        """
        self.client.connect(site_id=self.site_id)
        self.client.on_mycroft("speak", self.handle_speak)
        self.client.on_mycroft("hive.complete_intent_failure",
                               self.handle_intent_failure)
        self._connected = True
        LOG.info("== connected to HiveMind")
        LOG.warning(
            "a freshly registered HiveMind client is denied every message "
            "type until an admin runs `hivemind-core allow-msg "
            "recognizer_loop:utterance <client_id>` on the hub (and "
            "usually `speak` too). If messages seem to vanish silently, "
            "check that first."
        )

    def stop(self) -> None:
        try:
            self.transport.stop()
        except Exception:
            LOG.exception("error stopping WhatsApp transport")
        try:
            self.client.close()
        except Exception:
            LOG.exception("error closing HiveMind client")
        self._connected = False

    # ------------------------------------------------------------------
    # WhatsApp -> HiveMind
    # ------------------------------------------------------------------
    def _on_whatsapp_message(self, sender: str, text: str) -> None:
        """Callback handed to the transport for every inbound text message.

        Nothing is forwarded before the HiveMind handshake has completed
        -- forwarding earlier would get the connection killed by the hub
        instead of just failing the one message.
        """
        if not self._connected:
            LOG.warning("dropping WhatsApp message from %s, not connected "
                       "to HiveMind yet", sender)
            return
        self.forward_to_hivemind(text, sender)

    def forward_to_hivemind(self, text: str, from_number: str) -> None:
        msg = Message(
            "recognizer_loop:utterance",
            {"utterances": [text], "lang": self.lang},
            {
                "source": platform,
                "destination": "HiveMind",
                "platform": platform,
                "from_number": from_number,
                "user": {"phone_number": from_number},
                "session": {"session_id": f"whatsapp-{from_number}"},
            },
        )
        self.client.emit(HiveMessage(HiveMessageType.BUS, msg))

    # ------------------------------------------------------------------
    # HiveMind -> WhatsApp
    # ------------------------------------------------------------------
    def handle_speak(self, message: Message) -> None:
        to_number = message.context.get("from_number")
        if to_number is None:
            return
        utterance = message.data.get("utterance")
        if not utterance:
            return
        self.transport.send(to_number, utterance)

    def handle_intent_failure(self, message: Message) -> None:
        to_number = message.context.get("from_number")
        if to_number is None:
            return
        LOG.error("complete intent failure")
        self.transport.send(to_number, "I don't know how to answer that")


__all__ = ["HiveMindWhatsappBridge", "platform", "WhatsAppTransport"]
