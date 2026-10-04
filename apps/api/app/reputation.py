"""Phone-number reputation, shared across every wallet, carrier, and credit
union that reports into the same list.

There is no free, universal "is this a scammer" database — that data sits behind
paid partners. So the shared list is the real mechanism: when one person or one
credit union reports a number, it is flagged for everyone. Twilio Lookup can add
carrier and line-type when credentials are set, but the list stands on its own.
"""

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import FlaggedNumber, utcnow


def normalize(raw: str | None) -> str:
    """Canonical key for a number: its digits, US country code dropped. Empty
    string when the input is not phone-like."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) >= 7 else ""


def looks_like_number(raw: str | None) -> bool:
    return bool(normalize(raw))


async def lookup(session: AsyncSession, raw: str | None) -> dict:
    number = normalize(raw)
    if not number:
        return {"number": "", "flagged": False, "reports": 0, "source": None, "reason_en": None, "reason_es": None}
    row = await session.get(FlaggedNumber, number)
    if row is None:
        return {"number": number, "flagged": False, "reports": 0, "source": None, "reason_en": None, "reason_es": None}
    return {
        "number": number,
        "flagged": True,
        "reports": row.reports,
        "source": row.source,
        "reason_en": row.reason_en or None,
        "reason_es": row.reason_es or None,
    }


async def report(
    session: AsyncSession,
    raw: str | None,
    source: str = "community",
    reason_en: str = "",
    reason_es: str = "",
    commit: bool = True,
) -> dict:
    number = normalize(raw)
    if not number:
        return {"number": "", "flagged": False, "reports": 0, "source": None}
    now = utcnow()
    row = await session.get(FlaggedNumber, number)
    if row is None:
        row = FlaggedNumber(
            number=number,
            reports=1,
            source=source,
            reason_en=reason_en,
            reason_es=reason_es,
            first_seen=now,
            last_seen=now,
        )
        session.add(row)
    else:
        row.reports += 1
        row.last_seen = now
        if source == "credit_union":  # a named institution outranks a crowd report
            row.source = source
        if reason_en:
            row.reason_en = reason_en
        if reason_es:
            row.reason_es = reason_es
    if commit:
        await session.commit()
    return {"number": number, "flagged": True, "reports": row.reports, "source": row.source}


def reason_line(rep: dict, language: str) -> str:
    """A human sentence for a flagged number, with the live report count."""
    reports = rep.get("reports", 0)
    source = rep.get("source")
    if language == "es":
        if source == "credit_union":
            return f"Una cooperativa de crédito marcó este número. Reportado {reports} veces."
        return f"Otras personas ya reportaron este número como estafa: {reports} reportes."
    if source == "credit_union":
        return f"A credit union has flagged this number. Reported {reports} times."
    return f"Other people have already reported this number as a scam: {reports} reports."


async def enrich(raw: str | None) -> dict | None:
    """Best-effort carrier and line type from Twilio Lookup. Needs Twilio
    credentials; returns None without them or on any error."""
    number = normalize(raw)
    settings = get_settings()
    if not number or not settings.twilio_account_sid or not settings.twilio_auth_token:
        return None
    import httpx

    e164 = f"+1{number}" if len(number) == 10 else f"+{number}"
    url = f"https://lookups.twilio.com/v2/PhoneNumbers/{e164}"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                url,
                params={"Fields": "line_type_intelligence"},
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
            response.raise_for_status()
            data = response.json()
    except Exception:
        return None
    lti = data.get("line_type_intelligence") or {}
    return {"carrier": lti.get("carrier_name"), "line_type": lti.get("type")}
