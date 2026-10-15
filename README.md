# Lookout

A risky payment waits until someone you trust agrees.

Lookout sits between PayPal's approve step and the capture. It holds the authorization, compares what the person or their AI agent was shown with what PayPal was asked to approve, scores the message for scam pressure, and asks a trusted contact before any money is captured. Built for the PayPal AI Hackathon 2026 on the PayPal sandbox. No real money moves.

## Main application

- `apps/web` is the landing page, the wallet, and the trusted contact's phone.
- `apps/api` receives a payment check and returns allow, verify, or hold, and drives the PayPal order through authorize, capture, or void.

Open `/` for the front door. Open `/wallet` for Rosa, the account holder. Open `/trusted/maya-demo` for Maya, her trusted contact. On a wide screen the wallet sits in one phone. On a real phone it fills the screen.

## Data

- `apps/api/schema.sql` is the Tiger tables and the hourly chart.
- `apps/api/app/db.py` is the records: payments, approvals, reasons, watchers, pulse samples.
- `apps/api/app/samples` is the IRS text used in the demo.

## How a payment is decided

- `apps/api/app/labels.py` — Gemini, or the offline rules, reads the words.
- `apps/api/app/scoring.py` — the fixed score. One signal cannot hold a payment.
- `apps/api/app/why.py` — why the money is moving, ranked by threat and updated from a finished payment or a denial.
- `apps/api/app/desks` — watchers. A new file here can notice words and add one signal.
- `apps/api/app/service.py` — from the check to the decision, and the PayPal capture or void that follows it.
- `apps/api/app/redact.py` — codes are removed before anyone else sees them.

## PayPal

Lookout sits between PayPal's approve step and the capture. Money is held, never moved, until the check is done.

- `apps/api/app/paypal.py` — the PayPal REST client: AUTHORIZE orders, authorize, capture, void, and webhook signature checks. Credentials stay in this process.
- `apps/api/app/checkout.py` — the flow. `POST /paypal/orders` writes down what was shown before paying (amount, payee, page hash, the message) and returns PayPal's approve link. After approval, `POST /paypal/orders/{id}/authorize` holds the money, compares PayPal's facts with what was shown, and runs the scam check. A mismatch is a hold, no matter the score.
- Allow captures right away. Verify waits for the person. Hold waits for the trusted contact, who sees PayPal's amount and payee, not the agent's words. Deny, cancel, or timeout voids.
- `POST /paypal/webhooks` only accepts events signed with a certificate served by PayPal.
- `apps/api/scripts/paypal_smoke.py` is the sandbox check for a new app: create, approve, authorize, print the vault id, void.

Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `PAYPAL_WEBHOOK_ID` in `.env`. With none of them, the PayPal routes answer 503 and the rest of the wallet works as before.

## Keys

- `LOOKOUT_API_KEY` — when set, every API route except health and the signed webhooks needs it in `x-lookout-key`. The Next proxy adds it on the server, so the browser never holds it.
- `ELEVENLABS_WEBHOOK_SECRET` — when set, post-call transcripts must carry a valid `ElevenLabs-Signature`.
- `ALLOWED_ORIGINS` — browser origins allowed to call the API directly. Normally empty; the proxy is same-origin.

## Around the app

- `firmware/esp32` — the alarm light.
- `apps/vitals` — camera pulse, only from a real reading.
- `deploy/` — the host.
