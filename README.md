# Lookout

A risky payment waits until someone you trust agrees. This is a practice wallet!

## Main application

- `apps/web` is the landing page, the wallet, and the Lookout's phone.
- `apps/api` receives a payment check and returns allow, pause, or hold.

Open `/` for the door. Open `/wallet` for Rosa. Open `/crew/maya-demo` for Maya. On a wide screen the wallet sits in one phone. On a real phone it fills the screen.

## Data

- `apps/api/schema.sql` is the Tiger tables and the hourly chart.
- `apps/api/app/db.py` is the records: payments, approvals, reasons, watchers, pulse samples.
- `apps/api/app/samples` is the IRS text used in the demo.

## How a payment is decided

- `apps/api/app/labels.py` — Gemini, or the offline rules, reads the words.
- `apps/api/app/scoring.py` — the fixed score. One signal cannot hold a payment.
- `apps/api/app/why.py` — why the money is moving, ranked by threat and updated from a finished payment or a denial.
- `apps/api/app/desks` — watchers. A new file here can notice words and add one signal.
- `apps/api/app/service.py` — from the check to the Lookout's decision.
- `apps/api/app/redact.py` — codes are removed before anyone else sees them.

## Around the app

- `index.html` and `heist/` — the public crew film.
- `firmware/esp32` — the alarm light.
- `apps/vitals` — camera pulse, only from a real reading.
- `deploy/` — the host.
