FROM python:3.14-slim

WORKDIR /app
COPY . /app

# force the current hivemind-bus-client alpha rather than whatever a stale
# base layer might already have cached, since this bridge depends on the
# run_forever()-after-connect() fix and the current identity/handshake API
RUN pip install --no-cache-dir --upgrade "hivemind-bus-client>=1.0.13a1" \
    && pip install --no-cache-dir .

# credentials are passed as environment variables at `docker run` /
# compose time, never baked into the image.
ENV HIVEMIND_HOST=ws://127.0.0.1 \
    HIVEMIND_PORT=5678 \
    HIVEMIND_SITE_ID=whatsapp \
    HIVEMIND_LANG=en-us \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8080

EXPOSE 8080

ENTRYPOINT ["sh", "-c", "exec hivemind-whatsapp-bridge \
  --whatsapp-phone-number-id \"$WHATSAPP_PHONE_NUMBER_ID\" \
  --whatsapp-access-token \"$WHATSAPP_ACCESS_TOKEN\" \
  --whatsapp-verify-token \"$WHATSAPP_VERIFY_TOKEN\" \
  --web-host \"$WEB_HOST\" \
  --web-port \"$WEB_PORT\" \
  --access-key \"$HIVEMIND_ACCESS_KEY\" \
  --password \"$HIVEMIND_PASSWORD\" \
  --host \"$HIVEMIND_HOST\" \
  --hivemind-port \"$HIVEMIND_PORT\" \
  --site-id \"$HIVEMIND_SITE_ID\" \
  --lang \"$HIVEMIND_LANG\" \
  $EXTRA_ARGS"]
