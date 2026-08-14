"""Unit tests for the unofficial personal-account transport.

Exercises the real ``neonize`` client construction (offline: it never
calls ``connect()``, so no network/pairing happens) plus the message
filtering/extraction logic, using real ``neonize`` protobuf message
objects instead of mocks so the field names are verified against the
actual library, not a guess.

Skipped entirely if the ``personal`` extra (``neonize``) is not
installed -- it is optional, only the ``cloud`` transport is required.
"""
import os

import pytest

neonize = pytest.importorskip("neonize", reason="personal transport extra not installed")


@pytest.fixture()
def transport(tmp_path):
    from hivemind_whatsapp_bridge.transports.personal import PersonalTransport
    from neonize.client import NewClient

    client = NewClient(str(tmp_path / "session.sqlite3"))
    return PersonalTransport(session_dir=str(tmp_path), client=client)


def _make_message_event(text, sender="15551234567", from_me=False, is_group=False):
    from neonize.proto.Neonize_pb2 import JID, Message as MessageEv, MessageInfo, MessageSource
    from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message as E2EMessage

    return MessageEv(
        Info=MessageInfo(
            MessageSource=MessageSource(
                Sender=JID(User=sender, Server="s.whatsapp.net"),
                IsFromMe=from_me,
                IsGroup=is_group,
            ),
        ),
        Message=E2EMessage(conversation=text),
    )


def test_transport_builds_without_network_calls(transport):
    assert transport._client is not None


def test_inbound_text_message_invokes_handler(transport):
    received = []
    transport.set_message_handler(lambda sender, text: received.append((sender, text)))

    transport._handle_inbound(_make_message_event("turn on the lights"))

    assert received == [("15551234567", "turn on the lights")]


def test_group_message_is_ignored(transport):
    received = []
    transport.set_message_handler(lambda sender, text: received.append((sender, text)))

    transport._handle_inbound(_make_message_event("hello everyone", is_group=True))

    assert received == []


def test_own_outgoing_message_is_ignored(transport):
    received = []
    transport.set_message_handler(lambda sender, text: received.append((sender, text)))

    transport._handle_inbound(_make_message_event("hi", from_me=True))

    assert received == []


def test_inbound_before_handler_registered_does_not_raise(transport):
    transport._handle_inbound(_make_message_event("hello"))  # must not raise


def test_send_error_is_caught(transport, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("network error")

    monkeypatch.setattr(transport._client, "send_message", boom)
    transport.send("15551234567", "hi")  # must not raise


def test_session_dir_is_created(tmp_path):
    from hivemind_whatsapp_bridge.transports.personal import PersonalTransport
    from neonize.client import NewClient

    session_dir = tmp_path / "nested" / "session"
    client = NewClient(str(session_dir / "unused.sqlite3"))
    PersonalTransport(session_dir=str(session_dir), client=client)
    assert os.path.isdir(session_dir)
