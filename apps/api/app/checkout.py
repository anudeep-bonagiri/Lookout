"""PayPal checkout with a scam check between authorize and capture.

1. create_order: Lookout writes down what the person (or their agent) was
   shown before paying: amount, payee, the page hash, the message that asked
   for the money. It creates a PayPal order with intent AUTHORIZE and hands
   back PayPal's approve link. No money moves.
2. The buyer approves on PayPal's hosted page. PayPal never shows Lookout a
   password.
3. authorize: Lookout authorizes the order (money held, nothing captured),
   reads the facts PayPal returns (payee, amount), compares them with step 1,
   and runs the wallet's scam check on the attempt. Drift between what was
   shown and what PayPal authorized forces a hold. Allow captures right away;
   verify waits for the person; hold waits for the trusted contact.
4. service.settle captures on yes and voids on no, cancel, or timeout.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import app.paypal as paypal
import app.service as service
from app.config import get_settings
from app.db import PayPalOrder, dumps, loads, utcnow
from app.redact import redact

AMOUNT_TOLERANCE = 0.005


async def create_order(
    session: AsyncSession,
    user_id: str,
    amount: float,
    recipient: str,
    payee_email: str = "",
    prompt_text: str | None = None,
    page_hash: str = "",
    source_url: str = "",
    currency: str = "",
    vault_id: str = "",
    store_in_vault: bool = False,
    return_url: str = "",
    cancel_url: str = "",
) -> dict:
    user = await service._user(session, user_id)
    settings = get_settings()
    currency = (currency or settings.paypal_currency).upper()
    custom_id = str(uuid.uuid4())
    base = settings.public_base_url.rstrip("/")
    client = paypal.get_client()
    text = redact(prompt_text)
    order = await client.create_order(
        amount=amount,
        currency=currency,
        custom_id=custom_id,
        payee_email=payee_email,
        description=f"Lookout checked payment to {recipient}"[:127],
        return_url=return_url or (f"{base}/wallet?paypal=return&order=" if base else ""),
        cancel_url=cancel_url or (f"{base}/wallet?paypal=cancel" if base else ""),
        vault_id=vault_id,
        store_in_vault=store_in_vault,
    )
    if not order["id"]:
        raise paypal.PayPalError("PayPal returned no order id.")
    row = PayPalOrder(
        order_id=order["id"],
        user_id=user.id,
        recipient=recipient.strip(),
        payee_email=payee_email.strip().lower(),
        prompt_text=text,
        expected_amount=amount,
        currency=currency,
        page_hash=page_hash,
        source_url=source_url,
        vault_id=vault_id,
        status="created",
    )
    session.add(row)
    await session.commit()
    return {
        "order_id": row.order_id,
        "status": order["status"] or "CREATED",
        "approve_url": order["approve_url"],
        "expected_amount": amount,
        "currency": currency,
        "recipient": row.recipient,
    }


async def authorize(session: AsyncSession, order_id: str, user_id: str, on_call: bool = False) -> dict:
    row = await _owned_order(session, order_id, user_id)
    if row.status == "authorized" and row.attempt_id:
        return await service.get_attempt(session, row.attempt_id, user_id)
    if row.status == "created":
        client = paypal.get_client()
        auth = await client.authorize_order(order_id)
        row.authorization_id = auth.id
        row.authorized_amount = auth.amount
        row.authorized_payee = auth.payee_email or auth.payee_merchant_id
        if auth.vault_id:
            row.vault_id = auth.vault_id
        row.drift = dumps(_drift(row, auth))
        row.status = "authorized"
        row.updated_at = utcnow()
        # Written down before scoring, so a scorer failure can never lose track of held money.
        await session.commit()
    elif row.status != "authorized":
        raise PermissionError("This order is already decided.")
    drift = loads(row.drift, [])
    recipient = (row.authorized_payee or row.recipient)[:80]
    body = await service.check_payment(
        session,
        user_id,
        row.authorized_amount or row.expected_amount,
        recipient,
        "paypal",
        row.prompt_text,
        None,
        on_call,
        False,
        None,
        extra_signals={"context_drift": bool(drift)},
    )
    row.attempt_id = body["attempt_id"]
    await session.commit()
    if body["outcome"] == "allow":
        attempt = await service._attempt_by_id(session, row.attempt_id)
        await service.settle(session, attempt, release=True)
    body["paypal"] = service.paypal_view(row)
    return body


async def view(session: AsyncSession, order_id: str, user_id: str) -> dict:
    row = await _owned_order(session, order_id, user_id)
    if row.attempt_id:
        return await service.get_attempt(session, row.attempt_id, user_id)
    return {"attempt_id": None, "status": row.status, "paypal": service.paypal_view(row)}


async def apply_webhook(session: AsyncSession, event: dict) -> dict:
    """Mirror what PayPal says happened onto the order row. Verification is
    done by the caller; this only trusts the event because that passed."""
    event_type = str(event.get("event_type") or "")
    resource = event.get("resource") if isinstance(event.get("resource"), dict) else {}
    row = None
    if event_type == "CHECKOUT.ORDER.APPROVED":
        row = await session.get(PayPalOrder, str(resource.get("id") or ""))
        if row is not None and row.status == "created":
            row.status = "approved"
    elif event_type == "PAYMENT.AUTHORIZATION.VOIDED":
        row = await _by_authorization(session, str(resource.get("id") or ""))
        if row is not None and row.status in {"authorized", "void_failed"}:
            row.status = "voided"
    elif event_type == "PAYMENT.CAPTURE.COMPLETED":
        related = ((resource.get("supplementary_data") or {}).get("related_ids")) or {}
        row = await _by_authorization(session, str(related.get("authorization_id") or ""))
        if row is None and related.get("order_id"):
            row = await session.get(PayPalOrder, str(related["order_id"]))
        if row is not None and row.status in {"authorized", "capture_failed"}:
            row.status = "captured"
            row.capture_id = str(resource.get("id") or "") or row.capture_id
    if row is not None:
        row.updated_at = utcnow()
        await session.commit()
    return {"ok": True, "event_type": event_type, "handled": row is not None}


def _drift(row: PayPalOrder, auth: paypal.Authorization) -> list[dict]:
    found: list[dict] = []
    if abs(auth.amount - row.expected_amount) > AMOUNT_TOLERANCE:
        found.append({"field": "amount", "expected": row.expected_amount, "got": auth.amount})
    if auth.currency and auth.currency.upper() != row.currency.upper():
        found.append({"field": "currency", "expected": row.currency, "got": auth.currency})
    if row.payee_email and auth.payee_email and row.payee_email != auth.payee_email.lower():
        found.append({"field": "payee", "expected": row.payee_email, "got": auth.payee_email.lower()})
    return found


async def _owned_order(session: AsyncSession, order_id: str, user_id: str) -> PayPalOrder:
    user = await service._user(session, user_id)
    row = await session.get(PayPalOrder, order_id)
    if row is None:
        raise LookupError("That PayPal order was not found.")
    if row.user_id != user.id:
        raise PermissionError("That payment is not yours.")
    return row


async def _by_authorization(session: AsyncSession, authorization_id: str) -> PayPalOrder | None:
    if not authorization_id:
        return None
    from sqlalchemy import select

    return (
        await session.execute(select(PayPalOrder).where(PayPalOrder.authorization_id == authorization_id))
    ).scalars().first()
