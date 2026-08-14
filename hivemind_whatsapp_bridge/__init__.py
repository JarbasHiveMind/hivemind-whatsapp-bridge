"""HiveMind <-> WhatsApp bridge (WhatsApp Business Cloud API).

A HiveMind bridge is a satellite whose input and output are a chat
platform instead of a microphone. WhatsApp has no clean official API
for a personal account; this bridge targets Meta's **WhatsApp Business
Cloud API**, the only officially supported, ToS-safe path. It works the
same way the Twilio bridge does: Meta POSTs a webhook on inbound
messages, this bridge forwards the text onto the HiveMind bus, and the
hub's ``speak`` reply is sent back through the Cloud API's REST
endpoint.

There is a community alternative -- bridging to a `whatsmeow`/Baileys
gateway that pairs to a personal WhatsApp number via QR code -- and it
is documented in the README, but NOT implemented here: it talks to
WhatsApp's private client protocol rather than an API Meta publishes,
which is against WhatsApp's Terms of Service and can get the paired
number banned. Building the HiveMind side against that gateway is
straightforward (same shape as this file, swap the Cloud API HTTP calls
for calls to the gateway's REST/websocket API) but is left as a known,
documented option rather than something this repository fakes working.

Connection lifecycle, spelled out because getting it wrong is the
recurring bug across every HiveMind bridge written so far:

- ``HiveMessageBusClient.connect()`` already starts and owns the
  reconnect worker in a background thread, and blocks synchronously
  until the handshake completes (or fails). Call it exactly once. Do
  not also call ``run_forever()`` afterwards -- there is nothing left
  to start, the connection is already live in its own thread.
- Nothing is forwarded to HiveMind before ``connect()`` returns.
- host/port are configuration, not constants.
- a freshly registered HiveMind client is denied every message type
  until a hub admin runs ``hivemind-core allow-msg
  recognizer_loop:utterance <client_id>`` (and usually ``speak`` too);
  this bridge cannot do that step itself. See the README.
"""
from typing import Optional

import requests
from fastapi import FastAPI, Request, Response
from hivemind_bus_client import (
    HiveMessage,
    HiveMessageType,
    HiveMessageBusClient,
)
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

platform = "HiveMindWhatsappBridgeV0.1"

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class HiveMindWhatsappBridge:
    """Bridge WhatsApp (Business Cloud API) to a HiveMind node."""

    def __init__(self,
                 phone_number_id: Optional[str] = None,
                 access_token: Optional[str] = None,
                 verify_token: Optional[str] = None,
                 key: Optional[str] = None,
                 password: Optional[str] = None,
                 host: Optional[str] = None,
                 port: int = 5678,
                 self_signed: bool = False,
                 lang: str = "en-us",
                 site_id: str = "whatsapp",
                 *,
                 client: Optional[HiveMessageBusClient] = None,
                 session: Optional["requests.Session"] = None):
        """
        Parameters
        ----------
        phone_number_id: the WhatsApp Business phone number id from the
            Meta developer console, used to send replies.
        access_token: a Cloud API access token (temporary or permanent).
        verify_token: an arbitrary string you also set in the Meta
            webhook configuration; used to validate the webhook
            verification handshake (``GET /webhook``).
        key, password, host, port, self_signed: HiveMind hub connection.
        lang: default utterance language tag.
        site_id: this bridge's HiveMind site id.
        client: pre-built HiveMessageBusClient (tests / advanced setups).
        session: pre-built ``requests.Session`` (tests). When not given,
            a plain ``requests.Session`` is used to call the Graph API.
        """
        if session is None and not (phone_number_id and access_token):
            raise ValueError(
                "phone_number_id and access_token are required unless a "
                "session is injected"
            )

        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.verify_token = verify_token
        self.lang = lang
        self.site_id = site_id
        self.session = session or requests.Session()

        self.client = client or HiveMessageBusClient(
            key=key,
            password=password,
            host=host,
            port=port,
            useragent=platform,
            self_signed=self_signed,
        )
        self._connected = False

        self.app = FastAPI()
        self.app.add_api_route("/webhook", self.verify_webhook, methods=["GET"])
        self.app.add_api_route("/webhook", self.handle_webhook, methods=["POST"])

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
            self.client.close()
        except Exception:
            LOG.exception("error closing HiveMind client")
        self._connected = False

    # ------------------------------------------------------------------
    # WhatsApp -> HiveMind
    # ------------------------------------------------------------------
    async def verify_webhook(self, request: Request) -> Response:
        """Meta's webhook verification handshake (``GET /webhook``).

        Meta calls this once, with ``hub.verify_token``/``hub.challenge``
        query params, when you save the webhook config in the developer
        console. Echoing ``hub.challenge`` back confirms you control this
        endpoint; a mismatched token must be rejected.
        """
        params = request.query_params
        if (params.get("hub.mode") == "subscribe"
                and params.get("hub.verify_token") == self.verify_token):
            return Response(content=params.get("hub.challenge", ""))
        return Response(status_code=403)

    async def handle_webhook(self, request: Request) -> Response:
        """Inbound WhatsApp message webhook (``POST /webhook``).

        Cloud API payloads are nested:
        ``entry[].changes[].value.messages[]``. Only text messages are
        forwarded; anything else (images, reactions, status updates) is
        ignored. Nothing is forwarded before the HiveMind handshake has
        completed -- forwarding earlier would get the connection killed
        by the hub instead of just failing the one message. Meta expects
        a 200 response regardless of what the payload contained.
        """
        body = await request.json()
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for message in value.get("messages", []):
                    if message.get("type") != "text":
                        continue
                    text = message.get("text", {}).get("body")
                    sender = message.get("from")
                    if not text or not sender:
                        continue
                    if not self._connected:
                        LOG.warning("dropping WhatsApp message from %s, "
                                   "not connected to HiveMind yet", sender)
                        continue
                    self.forward_to_hivemind(text, sender)
        return Response(status_code=200)

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
        self.send_message(utterance, to_number)

    def handle_intent_failure(self, message: Message) -> None:
        to_number = message.context.get("from_number")
        if to_number is None:
            return
        LOG.error("complete intent failure")
        self.send_message("I don't know how to answer that", to_number)

    def send_message(self, text: str, to_number: str) -> None:
        """Send ``text`` back to ``to_number`` via the Cloud API.

        Called from the HiveMind bus's own worker thread; this is a
        plain blocking HTTP POST, so no extra scheduling is needed.
        """
        LOG.debug(f"Sending WhatsApp message to {to_number}: {text}")
        url = f"{GRAPH_API_BASE}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": text},
        }
        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception:
            LOG.exception(f"failed to send WhatsApp message to {to_number}")


__all__ = ["HiveMindWhatsappBridge", "platform"]
