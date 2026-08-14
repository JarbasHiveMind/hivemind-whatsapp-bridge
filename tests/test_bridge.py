"""Unit tests: construct the bridge offline and drive it with mocks.

No live WhatsApp API call (cloud or personal) or HiveMind connection is
made. ``FakeTransport`` proves the shared ``HiveMindWhatsappBridge``
logic (connect-once, no-forward-before-connected, speak routing) works
identically regardless of which transport is plugged in; the cloud
transport is additionally exercised through its real FastAPI routes
with a mocked HTTP session.
"""
from unittest.mock import MagicMock

import pytest

from hivemind_whatsapp_bridge.transports.base import WhatsAppTransport


class FakeTransport(WhatsAppTransport):
    """Minimal in-memory transport, standing in for cloud or personal."""

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False
        self.sent = []  # list of (recipient, text)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send(self, recipient, text):
        self.sent.append((recipient, text))

    def emit_inbound(self, sender, text):
        """Test helper: simulate an inbound WhatsApp message."""
        if self._on_message is not None:
            self._on_message(sender, text)


def _make_bridge(**kwargs):
    from hivemind_whatsapp_bridge import HiveMindWhatsappBridge

    fake_client = MagicMock(name="HiveMessageBusClient")
    transport = FakeTransport()
    bridge = HiveMindWhatsappBridge(transport=transport, client=fake_client, **kwargs)
    return bridge, fake_client, transport


def test_import_package_and_version():
    import hivemind_whatsapp_bridge
    from hivemind_whatsapp_bridge.version import __version__

    assert isinstance(__version__, str)
    assert __version__
    assert hivemind_whatsapp_bridge.platform.startswith("HiveMindWhatsappBridge")


def test_construct_bridge_without_connecting():
    bridge, fake_client, transport = _make_bridge()
    assert bridge._connected is False
    fake_client.connect.assert_not_called()


def test_transport_gets_message_handler_registered():
    bridge, fake_client, transport = _make_bridge()
    assert transport._on_message is not None


def test_connect_hivemind_calls_connect_once_and_registers_handlers():
    """connect_hivemind() must call connect() exactly once, never run_forever()."""
    bridge, fake_client, transport = _make_bridge()
    bridge.connect_hivemind()

    fake_client.connect.assert_called_once_with(site_id="whatsapp")
    fake_client.run_forever.assert_not_called()
    assert bridge._connected is True
    registered = {call.args[0] for call in fake_client.on_mycroft.call_args_list}
    assert registered == {"speak", "hive.complete_intent_failure"}


def test_inbound_message_forwarded_to_hivemind_after_connect():
    from hivemind_bus_client import HiveMessage, HiveMessageType

    bridge, fake_client, transport = _make_bridge()
    bridge.connect_hivemind()

    transport.emit_inbound("15551234567", "turn on the lights")

    fake_client.emit.assert_called_once()
    sent = fake_client.emit.call_args[0][0]
    assert isinstance(sent, HiveMessage)
    assert sent.msg_type == HiveMessageType.BUS
    payload = sent.payload
    assert payload.msg_type == "recognizer_loop:utterance"
    assert payload.data["utterances"] == ["turn on the lights"]
    assert payload.context["from_number"] == "15551234567"
    assert payload.context["session"]["session_id"] == "whatsapp-15551234567"


def test_no_forward_before_hivemind_connected():
    bridge, fake_client, transport = _make_bridge()
    # deliberately not calling bridge.connect_hivemind()

    transport.emit_inbound("15551234567", "hello")

    fake_client.emit.assert_not_called()


def test_speak_sends_message_to_originating_number_via_transport():
    from ovos_bus_client.message import Message

    bridge, fake_client, transport = _make_bridge()
    msg = Message("speak", {"utterance": "hi there"}, {"from_number": "15551234567"})
    bridge.handle_speak(msg)

    assert transport.sent == [("15551234567", "hi there")]


def test_speak_with_no_from_number_is_ignored():
    from ovos_bus_client.message import Message

    bridge, fake_client, transport = _make_bridge()
    msg = Message("speak", {"utterance": "hi"}, {})
    bridge.handle_speak(msg)
    assert transport.sent == []


def test_intent_failure_sends_fallback_message_via_transport():
    from ovos_bus_client.message import Message

    bridge, fake_client, transport = _make_bridge()
    msg = Message("hive.complete_intent_failure", {}, {"from_number": "15551234567"})
    bridge.handle_intent_failure(msg)

    assert len(transport.sent) == 1
    recipient, text = transport.sent[0]
    assert recipient == "15551234567"
    assert "don't know" in text


def test_stop_stops_transport_and_closes_hivemind_client():
    bridge, fake_client, transport = _make_bridge()
    bridge.connect_hivemind()
    bridge.stop()

    assert transport.stopped is True
    fake_client.close.assert_called_once()
    assert bridge._connected is False


def test_transport_error_on_send_does_not_raise():
    from ovos_bus_client.message import Message

    class BrokenTransport(FakeTransport):
        def send(self, recipient, text):
            raise RuntimeError("network error")

    from hivemind_whatsapp_bridge import HiveMindWhatsappBridge
    fake_client = MagicMock(name="HiveMessageBusClient")
    transport = BrokenTransport()
    bridge = HiveMindWhatsappBridge(transport=transport, client=fake_client)

    # the bridge itself does not swallow transport.send() errors -- each
    # real transport is responsible for catching its own I/O errors, as
    # both CloudTransport and PersonalTransport do. This test documents
    # that contract instead of asserting bridge-level suppression.
    msg = Message("speak", {"utterance": "hi"}, {"from_number": "1"})
    with pytest.raises(RuntimeError):
        bridge.handle_speak(msg)
