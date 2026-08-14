# HiveMind WhatsApp Bridge

This bridges WhatsApp to a HiveMind node using Meta's **WhatsApp
Business Cloud API**. A HiveMind bridge is a satellite whose input and
output are a chat platform instead of a microphone: WhatsApp messages
become HiveMind utterances, and the hub's spoken replies are sent back
as WhatsApp messages to the same conversation.

Read this section before anything else: WhatsApp has no clean official
API for a *personal* WhatsApp account. There are two real options, and
this repository is honest about which one it implements.

## The two paths, and why only one is implemented here

**Option A — WhatsApp Business Cloud API (implemented here).** Official,
run by Meta, webhook-based — the same shape as the Twilio bridge in
this org. What it needs:

- A Meta developer account and a Meta Business app with the WhatsApp
  product added.
- A WhatsApp Business phone number (Meta gives you one free test number
  during development; a real number for production).
- A publicly reachable webhook URL (this bridge exposes one).

This is the path this bridge is built against. It is clean, documented,
and does not risk your personal WhatsApp account.

**Option B — a `whatsmeow`/Baileys gateway paired to a personal
number via QR code.** Community-built, talks to WhatsApp's private
client protocol rather than an API Meta publishes. It technically works
today and is popular for personal-use bots, but it is against
WhatsApp's Terms of Service and Meta does ban numbers it detects doing
this, without warning and without appeal in many reported cases. This
repository does **not** implement this path and will not pretend a
QR-paired personal bridge is a supported, safe feature. If you still
want to go this route: run a `whatsmeow` (Go) or `Baileys`
(Node) gateway yourself, which exposes its own REST/webhook API once
paired, and adapt `hivemind_whatsapp_bridge/__init__.py`'s webhook
handler and `send_message()` to call that gateway's API instead of the
Graph API. The HiveMind-side logic (forward text in, `speak` replies
out, session keyed by sender) does not change; only the transport does.

This bridge has not been exercised against live Meta traffic or a real
HiveMind hub — only unit-tested with both sides mocked.

## Setting up the Cloud API (Option A) from scratch

1. Create a Meta developer account at
   [developers.facebook.com](https://developers.facebook.com).
2. Create an app (type "Business"), then add the **WhatsApp** product to
   it from the app dashboard.
3. Under WhatsApp → API Setup you get, for free during development: a
   temporary access token, a test phone number, and its **Phone number
   ID**. Note the phone number id and the access token.
4. The temporary token expires in 24 hours; for anything beyond a quick
   test, generate a permanent token: System Users (Business Settings) →
   create a system user → generate a token with the
   `whatsapp_business_messaging` permission.
5. To send messages to a real recipient during development, that
   recipient's number must be added to the test number's allowed
   recipient list (WhatsApp → API Setup → "To" field / manage phone
   number list). This restriction goes away once the app and a
   production number complete Meta's business verification.

## Pointing the Cloud API at this bridge

1. Run this bridge (see below) so it is listening, e.g. at
   `https://your-public-host/webhook`. Use a public server or a tunnel
   (e.g. `ngrok http 8080`) while testing locally.
2. In the app dashboard: WhatsApp → Configuration → Webhook → Edit.
   Set the Callback URL to `https://your-public-host/webhook` and the
   Verify Token to the same string you pass this bridge as
   `--whatsapp-verify-token`. Meta calls the URL once with a challenge
   to confirm you control it; this bridge answers that automatically.
3. Subscribe the webhook to the `messages` field.

## Registering the bridge on the hub

Every HiveMind client needs credentials and, separately, permission to
send the message types it uses. On the machine running `hivemind-core`:

```bash
hivemind-core add-client
```

This prints an access key and password; pass them to the bridge as
`--access-key` / `--password` (or store them once with
`hivemind-client set-identity` and omit the flags).

A freshly added client is denied every message type by default. The
bridge needs at least:

```bash
hivemind-core allow-msg recognizer_loop:utterance <client_id>
hivemind-core allow-msg speak <client_id>
```

`<client_id>` is printed by `add-client` (and by `hivemind-core
list-clients` afterwards). Skipping this step is the single most common
reason a bridge "connects fine" but nothing ever seems to happen: the
hub silently drops every message the client sends until it is
whitelisted.

## Running the bridge

```bash
pip install .
hivemind-whatsapp-bridge \
  --whatsapp-phone-number-id <id> \
  --whatsapp-access-token <token> \
  --whatsapp-verify-token <your-chosen-string> \
  --access-key <key> --password <password> \
  --host ws://127.0.0.1 --hivemind-port 5678
```

This starts a web server (default `0.0.0.0:8080`, override with
`--web-host` / `--web-port`) that Meta's webhook needs to reach.

Useful flags:

- `--site-id`: this bridge's HiveMind site id. If you run more than one
  bridge on the same host, give each a distinct site id — otherwise
  they collide over the same identity file and pinned peer keys.
- `--self-signed`: accept a self-signed TLS certificate on `wss://`
  hubs.
- `--lang`: the language tag attached to forwarded utterances (default
  `en-us`).

Run `hivemind-whatsapp-bridge --help` for the full list.

## Docker

```bash
docker build -t hivemind-whatsapp-bridge .
docker run --rm -p 8080:8080 \
  -e WHATSAPP_PHONE_NUMBER_ID=... \
  -e WHATSAPP_ACCESS_TOKEN=... \
  -e WHATSAPP_VERIFY_TOKEN=... \
  -e HIVEMIND_ACCESS_KEY=... \
  -e HIVEMIND_PASSWORD=... \
  -e HIVEMIND_HOST=ws://hivemind-core \
  hivemind-whatsapp-bridge
```

or via `docker-compose.yml` — copy it, fill in the environment section,
and `docker compose up`.

## What this bridge does, precisely

- Runs a FastAPI web server exposing `GET /webhook` (Meta's
  verification handshake) and `POST /webhook` (the actual message
  events), matching the Cloud API's webhook contract.
- Connects to the HiveMind hub with
  `hivemind_bus_client.HiveMessageBusClient`.
- Only forwards `text` messages; images, reactions, status updates and
  every other message type in the Cloud API payload are ignored.
- Drops anything received before the HiveMind handshake has completed —
  forwarding earlier would get the connection killed by the hub instead
  of just failing the one message.
- Forwards each remaining message as a `recognizer_loop:utterance` bus
  message, carrying the sender's WhatsApp number in the message context
  so the hub's `speak` reply can be routed back to the right
  conversation.
- Sends `speak` replies (and a fixed fallback line on
  `hive.complete_intent_failure`) back to the originating number via a
  plain HTTP POST to the Graph API's `/messages` endpoint.

## Testing

```bash
pip install -e .[test]
pytest tests/
```

The test suite mocks both the outbound HTTP session and the HiveMind
`HiveMessageBusClient`, so it runs without a live Meta app or a live
hub. It has not been exercised against real WhatsApp traffic or a real
HiveMind hub — that needs an actual Meta developer app and phone
number, which this repository does not have.
