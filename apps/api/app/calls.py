"""Place an outbound call so the agent rings the user's phone.

The app POSTs /voice/call; we ask Twilio's REST API to dial the user's number
and point the call at our own /voice/incoming TwiML — the same scam-check agent
the inbound line uses. No Twilio SDK: a single authenticated POST.

Needs a Twilio account SID, auth token, a from-number, and a public base URL
Twilio can fetch the TwiML from (your tunnel). Missing any of those, it returns
a friendly "setup" result so the button can explain what to connect.
"""

import httpx

from app.config import get_settings
from app.reputation import normalize


def _e164(raw: str | None) -> str:
    digits = normalize(raw)
    if not digits:
        return ""
    return f"+1{digits}" if len(digits) == 10 else f"+{digits}"


async def place_call(to: str, request_base_url: str = "") -> dict:
    settings = get_settings()
    to_e = _e164(to)
    from_e = _e164(settings.twilio_from_number)

    if not (settings.twilio_account_sid and settings.twilio_auth_token and from_e):
        return {"ok": False, "reason": "setup", "detail": "Connect a Twilio number (SID, token, and from-number) to turn this on."}
    base = (settings.public_base_url or request_base_url or "").rstrip("/")
    if not base.startswith("http"):
        return {"ok": False, "reason": "setup", "detail": "Set PUBLIC_BASE_URL to the public URL Twilio can reach (your tunnel)."}
    if not to_e:
        return {"ok": False, "reason": "bad_number", "detail": "That phone number did not look right."}

    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Calls.json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                data={"To": to_e, "From": from_e, "Url": f"{base}/voice/incoming"},
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
    except Exception as exc:
        return {"ok": False, "reason": "error", "detail": str(exc)[:200]}

    if response.status_code >= 400:
        detail = "Twilio refused the call."
        try:
            detail = str(response.json().get("message") or detail)[:200]
        except Exception:
            pass
        return {"ok": False, "reason": "twilio", "detail": detail}
    sid = ""
    try:
        sid = response.json().get("sid", "")
    except Exception:
        pass
    return {"ok": True, "sid": sid, "to": to_e}
