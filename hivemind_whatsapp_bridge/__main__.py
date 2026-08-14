"""CLI entry point for the HiveMind <-> WhatsApp bridge.

HiveMind identity (key/password/host/port) defaults to the values stored
by ``hivemind-client set-identity``; flags override them.

Two transports are available via ``--transport``:

- ``cloud`` (default): the official WhatsApp Business Cloud API.
- ``personal``: an unofficial, reverse-engineered client paired to a
  personal WhatsApp account. Read the "personal account (unofficial)"
  section of the README before using it -- it can get the paired number
  banned by Meta.
"""
import threading

import click
import uvicorn
from ovos_utils.log import LOG

from hivemind_whatsapp_bridge import HiveMindWhatsappBridge


def _build_transport(transport, whatsapp_phone_number_id, whatsapp_access_token,
                      whatsapp_verify_token, session_dir, qr_path):
    if transport == "cloud":
        from hivemind_whatsapp_bridge.transports.cloud import CloudTransport
        if not (whatsapp_phone_number_id and whatsapp_access_token and whatsapp_verify_token):
            raise click.UsageError(
                "--transport cloud requires --whatsapp-phone-number-id, "
                "--whatsapp-access-token and --whatsapp-verify-token")
        return CloudTransport(
            phone_number_id=whatsapp_phone_number_id,
            access_token=whatsapp_access_token,
            verify_token=whatsapp_verify_token,
        )
    elif transport == "personal":
        from hivemind_whatsapp_bridge.transports.personal import PersonalTransport
        return PersonalTransport(session_dir=session_dir, qr_path=qr_path)
    raise click.UsageError(f"unknown transport: {transport}")


def connect_whatsapp_to_hivemind(transport, key=None, password=None, host=None,
                                  port=5678, self_signed=False,
                                  lang="en-us", site_id="whatsapp"):
    bridge = HiveMindWhatsappBridge(
        transport=transport, key=key, password=password,
        host=host, port=port, self_signed=self_signed, lang=lang,
        site_id=site_id,
    )
    bridge.connect_hivemind()
    return bridge


@click.command()
@click.option("--transport", type=click.Choice(["cloud", "personal"]), default="cloud",
              help="WhatsApp integration path. 'cloud' (default) is the official, "
                   "ToS-compliant Business Cloud API. 'personal' pairs to a real "
                   "personal account via an unofficial, reverse-engineered client "
                   "-- read the README's risk section before using it.")
@click.option("--whatsapp-phone-number-id", default=None,
              help="[cloud] WhatsApp Business phone number id (Meta developer console)")
@click.option("--whatsapp-access-token", default=None,
              help="[cloud] WhatsApp Cloud API access token")
@click.option("--whatsapp-verify-token", default=None,
              help="[cloud] arbitrary string, must match the value set as "
                   "'Verify Token' in the Meta webhook configuration")
@click.option("--session-dir", default="./whatsapp_session",
              help="[personal] directory to persist the pairing session in, "
                   "so the bridge doesn't re-pair on every restart")
@click.option("--qr-path", default=None,
              help="[personal] where to also write the pairing QR code as a PNG "
                   "(default: <session-dir>/pairing_qr.png)")
@click.option("--web-host", default="0.0.0.0", help="[cloud] address to bind the webhook server to")
@click.option("--web-port", type=int, default=8080, help="[cloud] port to bind the webhook server to")
@click.option("--access-key", "key", default=None,
              help="HiveMind access key (default: from identity file)")
@click.option("--password", default=None,
              help="HiveMind password (default: from identity file)")
@click.option("--host", default=None,
              help="HiveMind host, e.g. ws://127.0.0.1 (default: from identity file)")
@click.option("--hivemind-port", "hive_port", type=int, default=5678,
              help="HiveMind port (default: 5678)")
@click.option("--site-id", default="whatsapp", help="this bridge's HiveMind site id")
@click.option("--self-signed", is_flag=True, help="accept self-signed SSL certificates")
@click.option("--lang", default="en-us", help="utterance language")
def main(transport, whatsapp_phone_number_id, whatsapp_access_token, whatsapp_verify_token,
         session_dir, qr_path, web_host, web_port, key, password, host, hive_port, site_id,
         self_signed, lang):
    """Bridge WhatsApp to a HiveMind node (Business Cloud API or a personal account)."""
    hive_host = host
    if hive_host and not hive_host.startswith("ws://") and not hive_host.startswith("wss://"):
        hive_host = "ws://" + hive_host

    wa_transport = _build_transport(
        transport, whatsapp_phone_number_id, whatsapp_access_token,
        whatsapp_verify_token, session_dir, qr_path)

    bridge = HiveMindWhatsappBridge(
        transport=wa_transport, key=key, password=password, host=hive_host,
        port=hive_port, self_signed=self_signed, lang=lang, site_id=site_id,
    )
    bridge.connect_hivemind()
    wa_transport.start()

    try:
        if transport == "cloud":
            LOG.info("set the Meta app's webhook callback URL to this bridge's "
                      "public URL + /webhook, and the verify token to the value "
                      "passed as --whatsapp-verify-token")
            LOG.info(f"bridge listening on {web_host}:{web_port}; press Ctrl-C to stop")
            uvicorn.run(wa_transport.app, host=web_host, port=web_port)
        else:
            LOG.info("personal-account transport running; scan the pairing QR "
                      "code above (or in %s) if this is the first run. "
                      "Press Ctrl-C to stop.", qr_path or f"{session_dir}/pairing_qr.png")
            stop_event = threading.Event()
            try:
                stop_event.wait()
            except KeyboardInterrupt:
                pass
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        bridge.stop()


if __name__ == '__main__':
    main()
