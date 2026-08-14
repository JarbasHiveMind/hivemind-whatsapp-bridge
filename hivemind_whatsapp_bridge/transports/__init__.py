"""WhatsApp transport implementations.

A transport is the only WhatsApp-specific part of this bridge. The
HiveMind-facing logic in :mod:`hivemind_whatsapp_bridge` (connect once,
never forward before the handshake completes, route ``speak`` back to
the originating chat) is identical regardless of which transport is
plugged in.

Two transports ship in this repository:

- :class:`~hivemind_whatsapp_bridge.transports.cloud.CloudTransport` --
  the official, ToS-compliant WhatsApp Business Cloud API (webhook in,
  REST out). This is the documented default.
- :class:`~hivemind_whatsapp_bridge.transports.personal.PersonalTransport`
  -- pairs to a personal WhatsApp account via the reverse-engineered
  multi-device protocol (through ``neonize``, Python bindings to
  ``whatsmeow``). This is unofficial, against WhatsApp's Terms of
  Service, and can get the paired number banned. See the README's
  "personal account (unofficial)" section before using it.
"""
from hivemind_whatsapp_bridge.transports.base import WhatsAppTransport

__all__ = ["WhatsAppTransport"]
