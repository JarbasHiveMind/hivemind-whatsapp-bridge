"""CLI entry point for the HiveMind <-> WhatsApp (Business Cloud API) bridge.

HiveMind identity (key/password/host/port) defaults to the values stored
by ``hivemind-client set-identity``; flags override them.
"""
import click
import uvicorn
from ovos_utils.log import LOG

from hivemind_whatsapp_bridge import HiveMindWhatsappBridge


def connect_whatsapp_to_hivemind(phone_number_id, access_token, verify_token,
                                  key=None, password=None, host=None,
                                  port=5678, self_signed=False,
                                  lang="en-us", site_id="whatsapp"):
    bridge = HiveMindWhatsappBridge(
        phone_number_id=phone_number_id, access_token=access_token,
        verify_token=verify_token, key=key, password=password,
        host=host, port=port, self_signed=self_signed, lang=lang,
        site_id=site_id,
    )
    bridge.connect_hivemind()
    return bridge


@click.command()
@click.option("--whatsapp-phone-number-id", required=True,
              help="WhatsApp Business phone number id (Meta developer console)")
@click.option("--whatsapp-access-token", required=True,
              help="WhatsApp Cloud API access token")
@click.option("--whatsapp-verify-token", required=True,
              help="arbitrary string, must match the value set as "
                   "'Verify Token' in the Meta webhook configuration")
@click.option("--web-host", default="0.0.0.0", help="address to bind the webhook server to")
@click.option("--web-port", type=int, default=8080, help="port to bind the webhook server to")
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
def main(whatsapp_phone_number_id, whatsapp_access_token, whatsapp_verify_token,
         web_host, web_port, key, password, host, hive_port, site_id,
         self_signed, lang):
    """Bridge WhatsApp (Business Cloud API) to a HiveMind node."""
    hive_host = host
    if hive_host and not hive_host.startswith("ws://") and not hive_host.startswith("wss://"):
        hive_host = "ws://" + hive_host

    bridge = connect_whatsapp_to_hivemind(
        phone_number_id=whatsapp_phone_number_id,
        access_token=whatsapp_access_token,
        verify_token=whatsapp_verify_token,
        key=key, password=password, host=hive_host, port=hive_port,
        self_signed=self_signed, lang=lang, site_id=site_id,
    )

    LOG.info("set the Meta app's webhook callback URL to this bridge's "
              "public URL + /webhook, and the verify token to the value "
              "passed as --whatsapp-verify-token")
    LOG.info(f"bridge listening on {web_host}:{web_port}; press Ctrl-C to stop")
    try:
        uvicorn.run(bridge.app, host=web_host, port=web_port)
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        bridge.stop()


if __name__ == '__main__':
    main()
