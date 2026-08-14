"""Unit tests for the WhatsApp Business Cloud API transport.

Drives the real FastAPI routes with a mocked ``requests.Session`` so no
live Meta call is made.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def _make_transport(**kwargs):
    from hivemind_whatsapp_bridge.transports.cloud import CloudTransport

    fake_session = MagicMock(name="requests.Session")
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_session.post.return_value = fake_resp

    transport = CloudTransport(session=fake_session, verify_token="secret", **kwargs)
    return transport, fake_session


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


def test_credentials_required_without_injected_session():
    from hivemind_whatsapp_bridge.transports.cloud import CloudTransport

    with pytest.raises(ValueError):
        CloudTransport()


def test_webhook_verification_echoes_challenge_on_matching_token():
    transport, _ = _make_transport()
    client = TestClient(transport.app)

    resp = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "secret",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 200
    assert resp.text == "12345"


def test_webhook_verification_rejects_mismatched_token():
    transport, _ = _make_transport()
    client = TestClient(transport.app)

    resp = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "wrong",
        "hub.challenge": "12345",
    })
    assert resp.status_code == 403


def test_inbound_text_message_invokes_handler():
    transport, _ = _make_transport()
    received = []
    transport.set_message_handler(lambda sender, text: received.append((sender, text)))

    client = TestClient(transport.app)
    resp = client.post("/webhook", json=_cloud_api_payload(
        text="turn on the lights", sender="15551234567"))

    assert resp.status_code == 200
    assert received == [("15551234567", "turn on the lights")]


def test_non_text_message_is_ignored():
    transport, _ = _make_transport()
    received = []
    transport.set_message_handler(lambda sender, text: received.append((sender, text)))

    client = TestClient(transport.app)
    resp = client.post("/webhook", json=_cloud_api_payload(msg_type="image"))

    assert resp.status_code == 200
    assert received == []


def test_inbound_before_handler_registered_does_not_raise():
    transport, _ = _make_transport()
    client = TestClient(transport.app)
    resp = client.post("/webhook", json=_cloud_api_payload())
    assert resp.status_code == 200


def test_send_posts_to_graph_api():
    transport, fake_session = _make_transport()
    transport.send("15551234567", "hi there")

    fake_session.post.assert_called_once()
    args, kwargs = fake_session.post.call_args
    assert kwargs["json"]["to"] == "15551234567"
    assert kwargs["json"]["text"]["body"] == "hi there"


def test_send_http_error_is_caught():
    transport, fake_session = _make_transport()
    fake_session.post.side_effect = RuntimeError("network error")

    transport.send("15551234567", "hello")  # must not raise
