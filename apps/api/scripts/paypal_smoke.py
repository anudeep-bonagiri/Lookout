"""Day-one sandbox check: does an AUTHORIZE order with vaulting work in this app?

Run from apps/api with PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env:

    .venv/bin/python scripts/paypal_smoke.py 1.00

It creates a $1.00 AUTHORIZE order asking PayPal to vault the buyer, prints the
approve link, waits for you to approve it with a sandbox buyer account, then
authorizes the order, prints what PayPal says (payee, amount, vault id), and
voids the authorization so nothing is captured.
"""

import asyncio
import sys
import uuid

sys.path.insert(0, ".")

import app.paypal as paypal  # noqa: E402


async def main(amount: float) -> None:
    client = paypal.get_client()
    custom_id = str(uuid.uuid4())
    order = await client.create_order(
        amount=amount,
        currency="USD",
        custom_id=custom_id,
        description="Lookout sandbox smoke test",
        return_url="https://example.com/return",
        cancel_url="https://example.com/cancel",
        store_in_vault=True,
    )
    print(f"order {order['id']} status {order['status']}")
    print(f"approve with a sandbox buyer: {order['approve_url']}")
    input("press Enter once PayPal shows the return page... ")
    auth = await client.authorize_order(order["id"])
    print(f"authorization {auth.id} status {auth.status}")
    print(f"amount {auth.amount} {auth.currency}")
    print(f"payee {auth.payee_email or auth.payee_merchant_id}")
    print(f"payer {auth.payer_email}")
    print(f"vault id {auth.vault_id or '(none: vaulting not enabled for this app)'}")
    print(f"expires {auth.expires_at}")
    await client.void(auth.id)
    print("voided; nothing captured")
    if auth.vault_id:
        print("vault works: Lookout can create later orders with payment_source.paypal.vault_id")
    await client.aclose()


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 1.00))
