# Deploy to api.stoptheheist.us

The apex `stoptheheist.us` stays on GitHub Pages (the crew film). The live app
and the Twilio call-in webhook run on the subdomain `api.stoptheheist.us`,
served by the docker-compose stack (api + web + Caddy with automatic HTTPS).

## 1. DNS (Porkbun)

Add one record. Leave the apex A records alone.

    Type: A    Host: api    Answer: <VM public IP>    TTL: 600

## 2. VM (any provider with a public IP; Vultr per the original plan)

- Ubuntu 22.04+, 1 vCPU / 1 GB is enough for the demo.
- Open inbound ports 80 and 443.
- Install Docker + the compose plugin.

## 3. Bring it up on the VM

    git clone https://github.com/anudeep-bonagiri/shinyhunters.git
    cd shinyhunters
    cp .env.example .env
    # edit .env, set at minimum:
    #   DOMAIN=api.stoptheheist.us
    #   PUBLIC_BASE_URL=https://api.stoptheheist.us
    #   TWILIO_ACCOUNT_SID=...        (fresh key)
    #   TWILIO_AUTH_TOKEN=...         (fresh key)
    #   TWILIO_FROM_NUMBER=+14327772545
    #   GEMINI_API_KEY=...           (optional, sharper replies)
    #   ELEVENLABS_API_KEY=...       (optional, nicer voice)
    sh deploy/up.sh

Caddy requests a Let's Encrypt certificate automatically once the A record
resolves to this host. Give DNS a few minutes to propagate first.

## 4. Point the Twilio number at it

Number +14327772545 (PhoneNumber SID PN2f18a4c6e94d6004b710fc1f7f690715).
Set the voice webhook to the subdomain, HTTP POST:

    https://api.stoptheheist.us/voice/incoming

This can be done from the Twilio Console (Phone Numbers -> the number -> Voice)
or with one authenticated API POST updating VoiceUrl / VoiceMethod.

## Notes

- The Caddyfile routes `/voice/*` to the FastAPI service and everything else to
  the Next app. Twilio hits `/voice/incoming` and `/voice/turn` directly; those
  must reach api:8000, which this routing handles.
- Inbound call-in works on a Twilio trial account (with a trial preamble before
  the TwiML). The outbound "call me" button only reaches verified numbers until
  the account is upgraded.
- With no TIGER_DATABASE_URL set, the api uses a sqlite file on a docker volume,
  which is fine for the demo. Set TIGER_DATABASE_URL to use Tiger/Postgres.
