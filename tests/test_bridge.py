"""Unit tests: construct the bridge offline and drive it with mocks.

No live WhatsApp Cloud API call or HiveMind connection is made. A
pre-built mock requests.Session and a pre-built mock
HiveMessageBusClient are injected so the bridge never touches the
network.
"""
import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _make_bridge(**kwargs):
    from hivemind_whatsapp_bridge import HiveMindWhatsappBridge

    fake_client = MagicMock(name="HiveMessageBusClient")
    fake_session = MagicMock(name="requests.Session")
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_session.post.return_value = fake_resp

    bridge = HiveMindWhatsappBridge(client=fake_client, session=fake_session,
                                    verify_token="secret", **kwargs)
    return bridge, fake_client, fake_session


def _cloud_api_payload(text="turn on the lights", sender="15551234567", msg_type="text"):
    message = {"from": sender, "type": msg_type}
    if msg_type == "text":
        message["text"] = {"body": text}
    return {
        "entry": [{
            "changes": [{
                "value": {"messages": [message]},
            }],
        }],
    }


def test_import_package_and_version():
    import hivemind_whatsapp_bridge
    from hivemind_whatsapp_bridge.version import __version__

    assert isinstance(__version__, str)
    assert __version__
    assert hivemind_whatsapp_bridge.platform.startswith("HiveMindWhatsappBridge")


def test_construct_bridge_without_connecting():
    bridge, fake_client, fake_session = _make_bridge()
    assert bridge._connected is False
    fake_client.connect.assert_not_called()


def test_credentials_required_without_injected_session():
    from hivemind_whatsapp_bridge import HiveMindWhatsappBridge

    with pytest.raises(ValueError):
        HiveMindWhatsappBridge(client=MagicMock())


def test_connect_hivemind_calls_connect_once_and_registers_handlers():
    """connect_hivemind() must call connect() exactly once, never run_forever()."""
    bridge, fake_client, fake_session = _make_bridge()
    bridge.connect_hivemind()

    fake_client.connect.assert_called_once_with(site_id="whatsapp")
    fake_client.run_forever.assert_not_called()
    assert bridge._connected is True
    registered = {call.args[0] for call in fake_client.on_mycroft.call_args_list}
    assert registered == {"speak", "hive.complete_intent_failure"}


def test_webhook_verification_echoes_challenge_on_matching_token():
    bridge, fake_client, fake_session = _make_bridge()
    client = TestClient(bridge.app)

    resp = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "secret",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_webhook_verification_rejects_mismatched_token():
    bridge, fake_client, fake_session = _make_bridge()
    client = TestClient(bridge.app)

    resp = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 403


def test_inbound_text_message_forwarded_to_hivemind_after_connect():
    from hivemind_bus_client import HiveMessage, HiveMessageType

    bridge, fake_client, fake_session = _make_bridge()
    bridge.connect_hivemind()

    client = TestClient(bridge.app)
    resp = client.post("/webhook", json=_cloud_api_payload(
        text="turn on the lights", sender="15551234567"))

    assert resp.status_code == 200
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
    bridge, fake_client, fake_session = _make_bridge()
    # deliberately not calling bridge.connect_hivemind()

    client = TestClient(bridge.app)
    resp = client.post("/webhook", json=_cloud_api_payload())

    assert resp.status_code == 200
    fake_client.emit.assert_not_called()


def test_non_text_message_is_ignored():
    bridge, fake_client, fake_session = _make_bridge()
    bridge.connect_hivemind()

    client = TestClient(bridge.app)
    resp = client.post("/webhook", json=_cloud_api_payload(msg_type="image"))

    assert resp.status_code == 200
    fake_client.emit.assert_not_called()


def test_speak_sends_message_to_originating_number():
    from ovos_bus_client.message import Message

    bridge, fake_client, fake_session = _make_bridge()
    msg = Message("speak", {"utterance": "hi there"}, {"from_number": "15551234567"})
    bridge.handle_speak(msg)

    fake_session.post.assert_called_once()
    args, kwargs = fake_session.post.call_args
    assert kwargs["json"]["to"] == "15551234567"
    assert kwargs["json"]["text"]["body"] == "hi there"


def test_speak_with_no_from_number_is_ignored():
    from ovos_bus_client.message import Message

    bridge, fake_client, fake_session = _make_bridge()
    msg = Message("speak", {"utterance": "hi"}, {})
    bridge.handle_speak(msg)
    fake_session.post.assert_not_called()


def test_intent_failure_sends_fallback_message():
    from ovos_bus_client.message import Message

    bridge, fake_client, fake_session = _make_bridge()
    msg = Message("hive.complete_intent_failure", {}, {"from_number": "15551234567"})
    bridge.handle_intent_failure(msg)

    fake_session.post.assert_called_once()
    _, kwargs = fake_session.post.call_args
    assert kwargs["json"]["to"] == "15551234567"
    assert "don't know" in kwargs["json"]["text"]["body"]


def test_send_message_http_error_is_caught():
    bridge, fake_client, fake_session = _make_bridge()
    fake_session.post.side_effect = RuntimeError("network error")

    bridge.send_message("hello", "15551234567")  # must not raise
