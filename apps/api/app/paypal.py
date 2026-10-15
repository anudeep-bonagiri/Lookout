"""A small PayPal REST client for the one thing Lookout needs from PayPal:
a real hold on money.

Orders are created with intent AUTHORIZE. After the buyer approves on
PayPal's own page, Lookout authorizes the order (funds held, nothing moved),
runs the scam check, and only then captures or voids. The agent or the wallet
page never touches these credentials; they live in this process only.

Everything here fails closed. No credentials means no PayPal call at all, and
an error from PayPal is raised, never swallowed into a capture.

Webhooks are verified locally (CRC32 of the body signed with the certificate
PayPal names in paypal-cert-url, host pinned to PayPal) because the sandbox
webhook simulator cannot be verified by the postback endpoint.
"""

import base64
import time
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlparse

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config import get_settings

BASES = {
    "sandbox": "https://api-m.sandbox.paypal.com",
    "live": "https://api-m.paypal.com",
}
CERT_HOSTS = {"api.paypal.com", "api.sandbox.paypal.com", "api-m.paypal.com", "api-m.sandbox.paypal.com"}


class PayPalUnavailable(RuntimeError):
    """PayPal is not configured. Nothing was attempted."""


class PayPalError(RuntimeError):
    """PayPal answered with an error. Nothing was captured."""


@dataclass
class Authorization:
    id: str
    status: str
    amount: float
    currency: str
    payee_email: str
    payee_merchant_id: str
    payer_email: str
    vault_id: str
    expires_at: str
    raw: dict = field(default_factory=dict, repr=False)


class PayPalClient:
    def __init__(self, client_id: str, client_secret: str, env: str = "sandbox") -> None:
        if not client_id or not client_secret:
            raise PayPalUnavailable("PayPal is not configured.")
        self.base = BASES.get(env, BASES["sandbox"])
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = ""
        self._token_expires = 0.0
        self._http = httpx.AsyncClient(base_url=self.base, timeout=20.0)

    async def token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        try:
            response = await self._http.post(
                "/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
            )
        except httpx.HTTPError as exc:
            raise PayPalError("PayPal could not be reached.") from exc
        if response.status_code != 200:
            raise PayPalError("PayPal rejected the app credentials.")
        data = response.json()
        self._token = str(data.get("access_token") or "")
        self._token_expires = time.time() + float(data.get("expires_in") or 0)
        if not self._token:
            raise PayPalError("PayPal returned no access token.")
        return self._token

    async def _call(self, method: str, path: str, json: dict | None = None, request_id: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {await self.token()}", "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            response = await self._http.request(method, path, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise PayPalError("PayPal could not be reached.") from exc
        if response.status_code == 204:
            return {}
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            issue = ""
            details = data.get("details") if isinstance(data, dict) else None
            if isinstance(details, list) and details:
                issue = str(details[0].get("issue") or details[0].get("description") or "")
            name = str(data.get("name") or response.status_code) if isinstance(data, dict) else str(response.status_code)
            raise PayPalError(f"PayPal said {name}{(': ' + issue) if issue else ''}.")
        return data if isinstance(data, dict) else {}

    async def create_order(
        self,
        amount: float,
        currency: str,
        custom_id: str,
        payee_email: str = "",
        description: str = "",
        return_url: str = "",
        cancel_url: str = "",
        vault_id: str = "",
        store_in_vault: bool = False,
    ) -> dict:
        unit: dict = {
            "reference_id": custom_id,
            "custom_id": custom_id,
            "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
        }
        if payee_email:
            unit["payee"] = {"email_address": payee_email}
        if description:
            unit["description"] = description[:127]
        paypal: dict = {}
        if vault_id:
            paypal["vault_id"] = vault_id
        else:
            context: dict = {
                "user_action": "PAY_NOW",
                "shipping_preference": "NO_SHIPPING",
                "brand_name": "Lookout",
            }
            if return_url:
                context["return_url"] = return_url
            if cancel_url:
                context["cancel_url"] = cancel_url
            paypal["experience_context"] = context
            if store_in_vault:
                paypal["attributes"] = {"vault": {"store_in_vault": "ON_SUCCESS", "usage_type": "MERCHANT"}}
        body = {"intent": "AUTHORIZE", "purchase_units": [unit], "payment_source": {"paypal": paypal}}
        data = await self._call("POST", "/v2/checkout/orders", body, request_id=custom_id)
        return {
            "id": str(data.get("id") or ""),
            "status": str(data.get("status") or ""),
            "approve_url": approve_link(data),
            "raw": data,
        }

    async def get_order(self, order_id: str) -> dict:
        return await self._call("GET", f"/v2/checkout/orders/{order_id}")

    async def authorize_order(self, order_id: str) -> Authorization:
        data = await self._call("POST", f"/v2/checkout/orders/{order_id}/authorize", {}, request_id=f"auth-{order_id}")
        return parse_authorization(data)

    async def capture(self, authorization_id: str) -> dict:
        data = await self._call(
            "POST",
            f"/v2/payments/authorizations/{authorization_id}/capture",
            {"final_capture": True},
            request_id=f"cap-{authorization_id}",
        )
        return {"id": str(data.get("id") or ""), "status": str(data.get("status") or ""), "raw": data}

    async def void(self, authorization_id: str) -> None:
        await self._call("POST", f"/v2/payments/authorizations/{authorization_id}/void", {})

    async def aclose(self) -> None:
        await self._http.aclose()


def approve_link(order: dict) -> str:
    links = order.get("links") if isinstance(order, dict) else None
    if not isinstance(links, list):
        return ""
    for rel in ("payer-action", "approve"):
        for link in links:
            if isinstance(link, dict) and link.get("rel") == rel and link.get("href"):
                return str(link["href"])
    return ""


def parse_authorization(order: dict) -> Authorization:
    units = order.get("purchase_units") or []
    unit = units[0] if units and isinstance(units[0], dict) else {}
    auths = ((unit.get("payments") or {}).get("authorizations")) or []
    auth = auths[0] if auths and isinstance(auths[0], dict) else {}
    if not auth.get("id"):
        raise PayPalError("PayPal returned no authorization for this order.")
    amount = auth.get("amount") or {}
    payee = unit.get("payee") or {}
    payer = order.get("payer") or {}
    source = ((order.get("payment_source") or {}).get("paypal")) or {}
    vault = ((source.get("attributes") or {}).get("vault")) or {}
    try:
        value = float(amount.get("value") or 0)
    except (TypeError, ValueError):
        value = 0.0
    return Authorization(
        id=str(auth["id"]),
        status=str(auth.get("status") or ""),
        amount=value,
        currency=str(amount.get("currency_code") or ""),
        payee_email=str(payee.get("email_address") or ""),
        payee_merchant_id=str(payee.get("merchant_id") or ""),
        payer_email=str(payer.get("email_address") or source.get("email_address") or ""),
        vault_id=str(vault.get("id") or ""),
        expires_at=str(auth.get("expiration_time") or ""),
        raw=order,
    )


@lru_cache
def _cached_client(client_id: str, client_secret: str, env: str) -> PayPalClient:
    return PayPalClient(client_id, client_secret, env)


def get_client() -> PayPalClient:
    """The process-wide client, built from settings. Raises PayPalUnavailable
    when no sandbox app is configured, so callers fail closed."""
    settings = get_settings()
    return _cached_client(settings.paypal_client_id, settings.paypal_client_secret, settings.paypal_env)


def configured() -> bool:
    settings = get_settings()
    return bool(settings.paypal_client_id and settings.paypal_client_secret)


# Webhook verification. PayPal signs "<transmission-id>|<transmission-time>|<webhook-id>|<crc32 of body>"
# with the key behind paypal-cert-url. We only trust certificates served from PayPal's own hosts.

_CERTS: dict[str, bytes] = {}


async def fetch_cert(url: str) -> bytes:
    if url in _CERTS:
        return _CERTS[url]
    async with httpx.AsyncClient(timeout=10.0) as http:
        response = await http.get(url)
    response.raise_for_status()
    _CERTS[url] = response.content
    return response.content


def cert_url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in CERT_HOSTS


def expected_message(transmission_id: str, transmission_time: str, webhook_id: str, body: bytes) -> str:
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}"


async def verify_webhook(headers: dict, body: bytes, webhook_id: str) -> bool:
    """True only when the signature checks out against a PayPal-hosted cert."""
    if not webhook_id:
        return False
    lower = {str(k).lower(): str(v) for k, v in headers.items()}
    transmission_id = lower.get("paypal-transmission-id", "")
    transmission_time = lower.get("paypal-transmission-time", "")
    cert_url = lower.get("paypal-cert-url", "")
    signature = lower.get("paypal-transmission-sig", "")
    algo = lower.get("paypal-auth-algo", "")
    if not (transmission_id and transmission_time and cert_url and signature):
        return False
    if algo and algo.upper() != "SHA256WITHRSA":
        return False
    if not cert_url_allowed(cert_url):
        return False
    try:
        pem = await fetch_cert(cert_url)
        cert = x509.load_pem_x509_certificate(pem)
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            return False
        message = expected_message(transmission_id, transmission_time, webhook_id, body).encode()
        key.verify(base64.b64decode(signature), message, padding.PKCS1v15(), hashes.SHA256())
        return True
    except Exception:
        return False
