"""WhatsApp Business Cloud API transport (official, ToS-compliant).

Meta POSTs a webhook on inbound messages; replies go out over the Cloud
API's REST endpoint. This is the documented default transport.
"""
from typing import Optional

import requests
from fastapi import FastAPI, Request, Response
from ovos_utils.log import LOG

from hivemind_whatsapp_bridge.transports.base import WhatsAppTransport

GRAPH_API_BASE = "https://graph.facebook.com/v19.0"


class CloudTransport(WhatsAppTransport):
    """Business Cloud API transport: webhook in, REST out."""

    def __init__(self,
                 phone_number_id: Optional[str] = None,
                 access_token: Optional[str] = None,
                 verify_token: Optional[str] = None,
                 *,
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
        session: pre-built ``requests.Session`` (tests). When not
            given, a plain ``requests.Session`` is used.
        """
        super().__init__()
        if session is None and not (phone_number_id and access_token):
            raise ValueError(
                "phone_number_id and access_token are required unless a "
                "session is injected"
            )
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.verify_token = verify_token
        self.session = session or requests.Session()

        self.app = FastAPI()
        self.app.add_api_route("/webhook", self.verify_webhook, methods=["GET"])
        self.app.add_api_route("/webhook", self.handle_webhook, methods=["POST"])

    # ------------------------------------------------------------------
    # WhatsAppTransport
    # ------------------------------------------------------------------
    def start(self) -> None:
        """No-op: the FastAPI app is served by ``__main__`` via uvicorn."""

    def stop(self) -> None:
        pass

    def send(self, recipient: str, text: str) -> None:
        """Send ``text`` back to ``recipient`` via the Cloud API.

        Plain blocking HTTP POST; called from the HiveMind bus's own
        worker thread, so no extra scheduling is needed.
        """
        LOG.debug(f"Sending WhatsApp message to {recipient}: {text}")
        url = f"{GRAPH_API_BASE}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": text},
        }
        try:
            resp = self.session.post(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
        except Exception:
            LOG.exception(f"failed to send WhatsApp message to {recipient}")

    # ------------------------------------------------------------------
    # FastAPI routes
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
        ignored. Meta expects a 200 response regardless of what the
        payload contained.
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
                    if self._on_message is not None:
                        self._on_message(sender, text)
        return Response(status_code=200)


__all__ = ["CloudTransport", "GRAPH_API_BASE"]
