# HiveMind WhatsApp Bridge

This bridges WhatsApp to a HiveMind node. A HiveMind bridge is a
satellite whose input and output are a chat platform instead of a
microphone: WhatsApp messages become HiveMind utterances, and the hub's
spoken replies are sent back as WhatsApp messages to the same
conversation.

There is no single official API for WhatsApp, so this bridge supports
**two interchangeable transports**, chosen with `--transport`:

| | `cloud` (default) | `personal` |
|---|---|---|
| What it is | Meta's official WhatsApp Business Cloud API | Pairs to a real personal number via the unofficial, reverse-engineered multi-device protocol (`neonize`/`whatsmeow`) |
| Status | Official, ToS-compliant | **Unofficial. Violates WhatsApp's Terms of Service.** |
| Risk | None beyond normal API usage | Meta can and does ban paired numbers, without warning |
| Setup | Meta developer app + webhook | Scan a QR code once, session persists |

Both transports feed the exact same HiveMind-side logic (forward text
in, `speak` replies out, session keyed by sender) through a small
`WhatsAppTransport` interface
(`hivemind_whatsapp_bridge/transports/base.py`). Adding a third
transport (e.g. a Baileys sidecar) means implementing that interface,
nothing else changes.

**Use `cloud` unless you have a specific reason not to.** `personal` is
documented below as a clearly-labeled, at-your-own-risk alternative for
people who want to bridge their own personal number and have accepted
the risk.

---

## Transport 1: `cloud` (WhatsApp Business Cloud API)

Official, run by Meta, webhook-based — the same shape as the Twilio
bridge in this org. What it needs:

- A Meta developer account and a Meta Business app with the WhatsApp
  product added.
- A WhatsApp Business phone number (Meta gives you one free test number
  during development; a real number for production).
- A publicly reachable webhook URL (this bridge exposes one).

### Setting it up from scratch

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

### Pointing the Cloud API at this bridge

1. Run this bridge (see "Running the bridge" below) so it is listening,
   e.g. at `https://your-public-host/webhook`. Use a public server or a
   tunnel (e.g. `ngrok http 8080`) while testing locally.
2. In the app dashboard: WhatsApp → Configuration → Webhook → Edit.
   Set the Callback URL to `https://your-public-host/webhook` and the
   Verify Token to the same string you pass this bridge as
   `--whatsapp-verify-token`. Meta calls the URL once with a challenge
   to confirm you control it; this bridge answers that automatically.
3. Subscribe the webhook to the `messages` field.

### What it does, precisely

- Runs a FastAPI web server exposing `GET /webhook` (Meta's
  verification handshake) and `POST /webhook` (the actual message
  events), matching the Cloud API's webhook contract.
- Only forwards `text` messages; images, reactions, status updates and
  every other message type in the Cloud API payload are ignored.
- Sends `speak` replies (and a fixed fallback line on
  `hive.complete_intent_failure`) back to the originating number via a
  plain HTTP POST to the Graph API's `/messages` endpoint.

---

## Transport 2: `personal` — read this before using it

This transport pairs to a real, personal WhatsApp number as a linked
device (WhatsApp Web/Desktop-style pairing), using the reverse-engineered
multi-device protocol via [`neonize`](https://github.com/krypton-byte/neonize)
(Python bindings over `whatsmeow`, the Go client also behind Baileys-class
tooling).

**State it plainly:**

- This is **unofficial**. It does not use any API published or
  supported by Meta.
- It **violates WhatsApp's Terms of Service**.
- Meta actively detects unofficial clients and **can, and does, ban the
  paired number** — permanently, without appeal, sometimes fast.
- **Use a throwaway/secondary number you can afford to lose.** Do not
  pair your primary personal number.
- This is a personal-use, per-conversation assistant bridge, the same
  shape as the `cloud` transport: it answers messages sent to the
  paired account, one chat at a time. It is not, and must not be turned
  into, a bulk-send or scraping tool. Group chats and the account's own
  outgoing messages are ignored on purpose.
- This is the same category of tool as `mautrix-whatsapp`,
  `go-whatsapp` and Baileys-based bridges: personal interoperability
  tooling, not a spam platform. That does not change the ToS or ban
  risk above — it is still the deployer's risk to accept.

### Pairing

1. Install the extra: `pip install .[personal]` (installs `neonize` and
   `segno`).
2. Run the bridge with `--transport personal --session-dir ./whatsapp_session`.
3. On first run, a QR code is printed to the terminal and also written
   as a PNG to `<session-dir>/pairing_qr.png`. On your phone: WhatsApp →
   Linked Devices → Link a Device → scan it.
4. Once paired, the session (pairing keys) is persisted to a sqlite
   database inside `--session-dir`. Keep that directory between
   restarts — deleting it means re-pairing (and issuing a new QR).

### What it does, precisely

- Connects via `neonize.client.NewClient`, using `--session-dir` as its
  sqlite session store.
- Registers handlers for the QR pairing event, the `Connected` event,
  and inbound `Message` events.
- Ignores messages from group chats and messages the account itself
  sent (`IsGroup` / `IsFromMe`), keeping the bridge a 1:1 assistant, not
  a broadcast surface.
- Extracts plain text from inbound messages (`neonize.utils.extract_text`)
  and forwards it the same way the `cloud` transport does.
- Sends `speak` replies back via `NewClient.send_message()`.

---

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

Cloud (default):

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

Personal (unofficial, read the section above first):

```bash
pip install .[personal]
hivemind-whatsapp-bridge \
  --transport personal --session-dir ./whatsapp_session \
  --access-key <key> --password <password> \
  --host ws://127.0.0.1 --hivemind-port 5678
```

Useful flags (both transports):

- `--site-id`: this bridge's HiveMind site id. If you run more than one
  bridge on the same host, give each a distinct site id — otherwise
  they collide over the same identity file and pinned peer keys.
- `--self-signed`: accept a self-signed TLS certificate on `wss://`
  hubs.
- `--lang`: the language tag attached to forwarded utterances (default
  `en-us`).

Run `hivemind-whatsapp-bridge --help` for the full list.

## Docker

Cloud:

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

Personal (mount a volume for `--session-dir` so pairing survives
container restarts, and run once interactively to scan the QR code):

```bash
docker build -t hivemind-whatsapp-bridge .
docker run --rm -it -v $(pwd)/whatsapp_session:/app/whatsapp_session \
  -e HIVEMIND_TRANSPORT=personal \
  -e HIVEMIND_SESSION_DIR=/app/whatsapp_session \
  -e HIVEMIND_ACCESS_KEY=... \
  -e HIVEMIND_PASSWORD=... \
  -e HIVEMIND_HOST=ws://hivemind-core \
  hivemind-whatsapp-bridge
```

or via `docker-compose.yml` — copy it, fill in the environment section
for the transport you're using (`whatsapp-bridge-cloud` or
`whatsapp-bridge-personal`), and `docker compose up <service>`.

## Testing

```bash
pip install -e .[test,personal]
pytest tests/
```

The test suite mocks the outbound HTTP session, the HiveMind
`HiveMessageBusClient`, and a fake `WhatsAppTransport`, so it runs
without a live Meta app, a live personal WhatsApp pairing, or a live
hub. It proves the shared bridge logic (connect-once, no-forward-before-
connected, `speak` routing) against both transport shapes, and each
transport's own request/response handling in isolation. It has not been
exercised against real WhatsApp traffic (Cloud API or personal) or a
real HiveMind hub — that needs an actual Meta developer app / a phone to
pair, and a running hub, none of which this repository has.
