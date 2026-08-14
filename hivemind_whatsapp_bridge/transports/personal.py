"""Personal-account WhatsApp transport (UNOFFICIAL -- read this first).

This transport pairs to a real, personal WhatsApp number the same way
WhatsApp Web does: as a linked device, using the reverse-engineered
multi-device protocol. It does not use any API published or supported
by Meta.

Consequences, stated plainly:

- This is against WhatsApp's Terms of Service.
- Meta actively detects unofficial clients and can, and does, ban the
  paired number -- permanently, without appeal, sometimes fast. Use a
  throwaway/secondary number you can afford to lose. Do not pair your
  primary personal number.
- This is a per-conversation assistant bridge: it answers messages sent
  to the paired account, one chat at a time, the same shape as the
  Cloud API transport. It is not, and must not be turned into, a
  bulk-send or scraping tool.
- The upstream implementation (``whatsmeow``, wrapped by ``neonize``) is
  the same reverse-engineered client family used by well known
  interoperability bridges (Baileys, go-whatsapp, mautrix-whatsapp) --
  this is the same category of tool, with the same risk profile.

Use the ``cloud`` transport unless you have a specific reason not to
and have accepted this risk.

Implementation: `neonize <https://github.com/krypton-byte/neonize>`_,
Python bindings over ``whatsmeow`` (Go). Chosen over a sidecar gateway
because it needs no second service/container and no extra network hop
-- the whole bridge stays a single Python process. Session state
(pairing keys) persists to a sqlite database under ``session_dir`` so
re-pairing is only needed once.
"""
import os
import threading
from typing import Optional

from ovos_utils.log import LOG

from hivemind_whatsapp_bridge.transports.base import WhatsAppTransport

RISK_WARNING = (
    "PersonalTransport uses an UNOFFICIAL, reverse-engineered WhatsApp "
    "client. This violates WhatsApp's Terms of Service and Meta can ban "
    "the paired number, permanently and without warning. Use a "
    "throwaway/secondary number. This is the deployer's risk to accept. "
    "See the README before using this transport in anything you care about."
)


class PersonalTransport(WhatsAppTransport):
    """Personal WhatsApp account transport, via ``neonize``/``whatsmeow``."""

    def __init__(self,
                 session_dir: str = "./whatsapp_session",
                 qr_path: Optional[str] = None,
                 *,
                 client=None):
        """
        Parameters
        ----------
        session_dir: directory used to persist the pairing session
            (sqlite database). Created if missing. Reusing the same
            directory across restarts avoids re-pairing.
        qr_path: where to also write the pairing QR code as a PNG, in
            addition to printing it to the terminal. Defaults to
            ``<session_dir>/pairing_qr.png``.
        client: pre-built ``neonize.client.NewClient`` (tests / advanced
            setups). When not given, a real client is constructed and
            ``neonize`` must be installed (``pip install neonize``).
        """
        super().__init__()
        LOG.warning(RISK_WARNING)

        self.session_dir = session_dir
        os.makedirs(session_dir, exist_ok=True)
        self.qr_path = qr_path or os.path.join(session_dir, "pairing_qr.png")
        self._thread: Optional[threading.Thread] = None

        self._client = client or self._build_client()
        self._register_handlers()

    def _build_client(self):
        # imported lazily: neonize ships a compiled Go extension and is
        # only required for this transport, not for the cloud one.
        from neonize.client import NewClient
        db_path = os.path.join(self.session_dir, "session.sqlite3")
        return NewClient(db_path)

    def _register_handlers(self) -> None:
        from neonize.events import ConnectedEv, MessageEv

        client = self._client

        @client.event.qr
        def _on_qr(_client, qr_bytes: bytes) -> None:
            LOG.info("WhatsApp pairing required: scan this QR code with "
                      "WhatsApp > Linked Devices > Link a Device. Also "
                      "written to %s", self.qr_path)
            try:
                import segno
                segno.make_qr(qr_bytes).save(self.qr_path, scale=5)
                segno.make_qr(qr_bytes).terminal(compact=True)
            except Exception:
                LOG.exception("failed to render/save pairing QR code")

        @client.event(ConnectedEv)
        def _on_connected(_client, _event) -> None:
            LOG.info("paired and connected to WhatsApp (personal account, "
                      "unofficial transport)")

        @client.event(MessageEv)
        def _on_message(_client, message) -> None:
            self._handle_inbound(message)

    def _handle_inbound(self, message) -> None:
        from neonize.utils import extract_text

        info = message.Info
        source = info.MessageSource
        if source.IsFromMe or source.IsGroup:
            # per-conversation assistant only: ignore our own echoes and
            # group chats, never turn this into a broadcast/bulk surface.
            return
        text = extract_text(message.Message)
        sender = source.Sender.User
        if not text or not sender:
            return
        if self._on_message is not None:
            self._on_message(sender, text)

    # ------------------------------------------------------------------
    # WhatsAppTransport
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Connect (and pair, if no session is persisted yet).

        ``NewClient.connect()`` blocks for the lifetime of the
        connection, so it runs on its own daemon thread and this method
        returns immediately, matching the transport contract.
        """
        self._thread = threading.Thread(
            target=self._client.connect, name="whatsapp-personal", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        try:
            self._client.disconnect()
        except Exception:
            LOG.exception("error disconnecting personal WhatsApp transport")

    def send(self, recipient: str, text: str) -> None:
        from neonize.utils import build_jid

        try:
            self._client.send_message(build_jid(recipient), text)
        except Exception:
            LOG.exception(f"failed to send WhatsApp message to {recipient}")


__all__ = ["PersonalTransport", "RISK_WARNING"]
