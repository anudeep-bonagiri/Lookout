import base64
import datetime as dt
import hashlib
import hmac
import json
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from httpx import ASGITransport, AsyncClient

import app.paypal as paypal
from app.config import get_settings
from app.db import init_db, session_factory
from app.main import create_app, elevenlabs_signed
from app.service import ROSA_ID, seed

BENIGN = "Order page: Sony wireless headphones, $49.00, ships in two days."
GEEK_SQUAD = (
    "Your Geek Squad subscription renewed for $399.99. If you did not authorize this call "
    "800-555-0111 within 24 hours or the charge is final. Do not contact your bank."
)


class FakePayPal:
    """Stands in for PayPal sandbox: remembers orders, authorizes for whatever
    amount the test says PayPal actually saw, and records captures and voids."""

    def __init__(self) -> None:
        self.orders: dict[str, dict] = {}
        self.authorized_amount: float | None = None
        self.captures: list[str] = []
        self.voids: list[str] = []
        self.fail_capture = False
        self.counter = 0

    async def create_order(self, amount, currency, custom_id, payee_email="", **_kw):
        self.counter += 1
        order_id = f"ORDER{self.counter}"
        self.orders[order_id] = {"amount": amount, "currency": currency, "payee": payee_email}
        return {"id": order_id, "status": "PAYER_ACTION_REQUIRED", "approve_url": f"https://sandbox.paypal.com/checkoutnow?token={order_id}", "raw": {}}

    async def authorize_order(self, order_id):
        order = self.orders[order_id]
        amount = self.authorized_amount if self.authorized_amount is not None else order["amount"]
        return paypal.Authorization(
            id=f"AUTH-{order_id}",
            status="CREATED",
            amount=amount,
            currency=order["currency"],
            payee_email=order["payee"] or "seller@example.com",
            payee_merchant_id="MERCHANT1",
            payer_email="rosa@example.com",
            vault_id="",
            expires_at="",
        )

    async def capture(self, authorization_id):
        if self.fail_capture:
            raise paypal.PayPalError("PayPal said AUTHORIZATION_EXPIRED.")
        self.captures.append(authorization_id)
        return {"id": f"CAP-{authorization_id}", "status": "COMPLETED", "raw": {}}

    async def void(self, authorization_id):
        self.voids.append(authorization_id)


@pytest.fixture
async def client(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    get_settings.cache_clear()
    app = create_app(url)
    await init_db()
    factory = session_factory()
    async with factory() as session:
        await seed(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def fake(monkeypatch):
    stub = FakePayPal()
    monkeypatch.setattr(paypal, "get_client", lambda: stub)
    monkeypatch.setattr(paypal, "configured", lambda: True)
    return stub


async def _order(client, amount=49.0, payee="headphones@example.com", text=BENIGN, **extra):
    response = await client.post(
        "/paypal/orders",
        json={
            "user_id": ROSA_ID,
            "amount": amount,
            "recipient": "Sony Store",
            "payee_email": payee,
            "prompt_text": text,
            "page_hash": "a" * 64,
            "source_url": "https://shop.example.com/headphones",
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
async def test_without_a_sandbox_app_nothing_is_attempted(client: AsyncClient):
    response = await client.post(
        "/paypal/orders",
        json={"user_id": ROSA_ID, "amount": 49, "recipient": "Sony Store", "prompt_text": BENIGN},
    )
    assert response.status_code == 503
    health = await client.get("/health")
    assert health.json()["paypal"] is False


@pytest.mark.asyncio
async def test_matching_order_is_captured_after_the_check(client: AsyncClient, fake: FakePayPal):
    order = await _order(client)
    assert order["approve_url"].startswith("https://sandbox.paypal.com/")
    assert fake.captures == []

    done = await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": ROSA_ID})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["method"] == "paypal"
    assert body["outcome"] == "allow"
    assert body["recipient"] == "headphones@example.com"
    assert body["signals"]["context_drift"] is False
    assert body["paypal"]["status"] == "captured"
    assert body["paypal"]["drift"] == []
    assert fake.captures == ["AUTH-ORDER1"]
    assert fake.voids == []


@pytest.mark.asyncio
async def test_amount_drift_holds_and_a_denial_voids(client: AsyncClient, fake: FakePayPal):
    order = await _order(client, amount=49.0)
    fake.authorized_amount = 5000.0

    held = await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": ROSA_ID})
    assert held.status_code == 200, held.text
    body = held.json()
    assert body["outcome"] == "hold"
    assert body["stage"] == 4
    assert body["signals"]["context_drift"] is True
    assert any("does not match" in reason for reason in body["reasons"])
    assert body["paypal"]["status"] == "authorized"
    assert body["paypal"]["drift"] == [{"field": "amount", "expected": 49.0, "got": 5000.0}]
    assert fake.captures == []

    blocked = await client.post(f"/attempts/{body['attempt_id']}/continue", json={"user_id": ROSA_ID})
    assert blocked.status_code == 400

    crew = await client.get("/crew/maya-demo")
    pending = crew.json()["pending"]
    assert pending["approval_id"] == body["approval_id"]
    assert "$5,000" in pending["fact"]
    assert "PayPal" in pending["fact"]

    denied = await client.post(
        f"/approvals/{body['approval_id']}/decide",
        json={"token": "maya-demo", "decision": "denied"},
    )
    assert denied.status_code == 200
    assert denied.json()["paypal"]["status"] == "voided"
    assert fake.voids == ["AUTH-ORDER1"]
    assert fake.captures == []

    again = await client.get(f"/paypal/orders/{order['order_id']}", params={"user_id": ROSA_ID})
    assert again.json()["status"] == "denied"
    assert again.json()["paypal"]["status"] == "voided"


@pytest.mark.asyncio
async def test_contact_approval_captures_a_held_order(client: AsyncClient, fake: FakePayPal):
    order = await _order(client, amount=399.99, payee="billing@example.com", text=GEEK_SQUAD)
    held = await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": ROSA_ID})
    body = held.json()
    assert body["outcome"] == "hold", body
    assert body["signals"]["context_drift"] is False
    approved = await client.post(
        f"/approvals/{body['approval_id']}/decide",
        json={"token": "maya-demo", "decision": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["paypal"]["status"] == "captured"
    assert fake.captures == ["AUTH-ORDER1"]


@pytest.mark.asyncio
async def test_capture_failure_leaves_money_where_it_is(client: AsyncClient, fake: FakePayPal):
    order = await _order(client, amount=399.99, payee="billing@example.com", text=GEEK_SQUAD)
    body = (await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": ROSA_ID})).json()
    fake.fail_capture = True
    approved = await client.post(
        f"/approvals/{body['approval_id']}/decide",
        json={"token": "maya-demo", "decision": "approved"},
    )
    assert approved.status_code == 200
    assert approved.json()["paypal"]["status"] == "capture_failed"
    assert "AUTHORIZATION_EXPIRED" in approved.json()["paypal"]["error"]
    assert fake.captures == []


@pytest.mark.asyncio
async def test_cancel_voids_and_a_stranger_cannot_touch_the_order(client: AsyncClient, fake: FakePayPal):
    order = await _order(client, amount=399.99, payee="billing@example.com", text=GEEK_SQUAD)
    stranger = await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": "nobody"})
    assert stranger.status_code == 404
    body = (await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": ROSA_ID})).json()
    cancelled = await client.post(f"/attempts/{body['attempt_id']}/cancel", json={"user_id": ROSA_ID})
    assert cancelled.status_code == 200
    assert cancelled.json()["paypal"]["status"] == "voided"
    assert fake.voids == ["AUTH-ORDER1"]


# Webhooks: a real RSA signature over the CRC32 message, with a cert we mint here.


def _self_signed() -> tuple[rsa.RSAPrivateKey, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "messageverificationcerts.sandbox.paypal.com")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM)


def _signed_headers(key: rsa.RSAPrivateKey, body: bytes, webhook_id: str, cert_url: str) -> dict:
    tid = "7a8b9c00-1111-2222-3333-444455556666"
    ttime = "2026-10-14T12:00:00Z"
    message = paypal.expected_message(tid, ttime, webhook_id, body).encode()
    sig = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    return {
        "paypal-transmission-id": tid,
        "paypal-transmission-time": ttime,
        "paypal-cert-url": cert_url,
        "paypal-auth-algo": "SHA256withRSA",
        "paypal-transmission-sig": base64.b64encode(sig).decode(),
        "content-type": "application/json",
    }


@pytest.fixture
def signer(monkeypatch):
    key, pem = _self_signed()

    async def fetch(url: str) -> bytes:
        return pem

    monkeypatch.setattr(paypal, "fetch_cert", fetch)
    monkeypatch.setenv("PAYPAL_WEBHOOK_ID", "WH-TEST")
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


CERT_URL = "https://api.sandbox.paypal.com/v1/notifications/certs/CERT-TEST"


@pytest.mark.asyncio
async def test_signed_void_webhook_updates_the_order(client: AsyncClient, fake: FakePayPal, signer):
    order = await _order(client, amount=399.99, payee="billing@example.com", text=GEEK_SQUAD)
    body = (await client.post(f"/paypal/orders/{order['order_id']}/authorize", json={"user_id": ROSA_ID})).json()
    assert body["paypal"]["status"] == "authorized"
    event = json.dumps({"event_type": "PAYMENT.AUTHORIZATION.VOIDED", "resource": {"id": "AUTH-ORDER1"}}).encode()
    response = await client.post("/paypal/webhooks", content=event, headers=_signed_headers(signer, event, "WH-TEST", CERT_URL))
    assert response.status_code == 200, response.text
    assert response.json()["handled"] is True
    view = await client.get(f"/paypal/orders/{order['order_id']}", params={"user_id": ROSA_ID})
    assert view.json()["paypal"]["status"] == "voided"


@pytest.mark.asyncio
async def test_tampered_or_foreign_webhooks_are_rejected(client: AsyncClient, signer):
    event = json.dumps({"event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "X"}}).encode()
    headers = _signed_headers(signer, event, "WH-TEST", CERT_URL)
    tampered = await client.post("/paypal/webhooks", content=event + b" ", headers=headers)
    assert tampered.status_code == 400
    wrong_webhook = await client.post("/paypal/webhooks", content=event, headers=_signed_headers(signer, event, "WH-OTHER", CERT_URL))
    assert wrong_webhook.status_code == 400
    foreign = await client.post(
        "/paypal/webhooks", content=event, headers=_signed_headers(signer, event, "WH-TEST", "https://evil.example.com/cert.pem")
    )
    assert foreign.status_code == 400
    unsigned = await client.post("/paypal/webhooks", content=event)
    assert unsigned.status_code == 400


@pytest.mark.asyncio
async def test_webhooks_are_refused_when_no_webhook_id_is_set(client: AsyncClient, signer, monkeypatch):
    monkeypatch.delenv("PAYPAL_WEBHOOK_ID")
    get_settings.cache_clear()
    event = b'{"event_type":"PAYMENT.AUTHORIZATION.VOIDED","resource":{"id":"AUTH-1"}}'
    response = await client.post("/paypal/webhooks", content=event, headers=_signed_headers(signer, event, "", CERT_URL))
    assert response.status_code == 400


# Shared key and ElevenLabs signing.


@pytest.mark.asyncio
async def test_api_key_gates_everything_but_webhooks(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOKOUT_API_KEY", "test-key")
    get_settings.cache_clear()
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'k.db'}")
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        assert (await http.get("/health")).status_code == 200
        assert (await http.get("/reasons")).status_code == 401
        assert (await http.get("/reasons", headers={"x-lookout-key": "wrong"})).status_code == 401
        assert (await http.get("/reasons", headers={"x-lookout-key": "test-key"})).status_code == 200
        assert (await http.post("/paypal/webhooks", content=b"{}")).status_code == 400
    get_settings.cache_clear()


def test_elevenlabs_signature_check():
    secret = "wsec_test"
    body = b'{"data":{"conversation_id":"c1"}}'
    stamp = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    assert elevenlabs_signed(f"t={stamp},v0={digest}", body, secret)
    assert not elevenlabs_signed(f"t={stamp},v0={digest}", body + b"x", secret)
    assert not elevenlabs_signed(f"t={stamp},v0={digest}", body, "other")
    old = str(int(time.time()) - 3600)
    old_digest = hmac.new(secret.encode(), f"{old}.".encode() + body, hashlib.sha256).hexdigest()
    assert not elevenlabs_signed(f"t={old},v0={old_digest}", body, secret)
    assert not elevenlabs_signed("", body, secret)


@pytest.mark.asyncio
async def test_unsigned_transcript_is_refused_when_a_secret_is_set(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_WEBHOOK_SECRET", "wsec_test")
    get_settings.cache_clear()
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'e.db'}")
    await init_db()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        refused = await http.post("/voice/transcript", content=b"{}", headers={"content-type": "application/json"})
        assert refused.status_code == 401
        body = b'{"data":{"conversation_id":"c1","transcript":[]}}'
        stamp = str(int(time.time()))
        digest = hmac.new(b"wsec_test", f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
        accepted = await http.post(
            "/voice/transcript",
            content=body,
            headers={"content-type": "application/json", "elevenlabs-signature": f"t={stamp},v0={digest}"},
        )
        assert accepted.status_code == 200, accepted.text
    get_settings.cache_clear()
