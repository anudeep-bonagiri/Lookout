import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import (
    ApprovalRequest,
    Contact,
    FlaggedNumber,
    PaymentAttempt,
    ReasonBelief,
    ReasonObservation,
    RiskCheck,
    User,
    VitalsSample,
    Watcher,
    as_utc,
    dumps,
    loads,
    utcnow,
)
import app.reputation as reputation
from app.labels import MESSAGE_SIGNALS, decode_image, label_message, normalize_recipient
from app.pressure import pressure_status
from app.reasons import ACTION, METHOD_LABELS, POINTS, UNKNOWN, warning_for
from app.scoring import score_signals, user_may_continue, wallet_signals
from app.watchers import DESKS, apply_watchers, ledger_line, load_desks, reader_line, reason_line
from app.why import apply as apply_why
from app.why import known as known_why
from app.why import rank as rank_reasons, reason_sentence, review_note, suggest

ROSA_ID = "11111111-1111-4111-8111-111111111111"
MAYA_ID = "22222222-2222-4222-8222-222222222222"
MAYA_TOKEN = "maya-demo"

HISTORY_STATUSES = ("allowed", "approved", "seed")


SEED_FLAGGED = [
    ("202-555-0147", 38, "community", "Caller claims to be the IRS and demands gift cards.", "Dice ser del IRS y exige tarjetas de regalo."),
    ("800-555-0111", 12, "credit_union", "Flagged by a credit union for a fake fraud-department call.", "Marcado por una cooperativa de crédito por una llamada falsa de 'fraude'."),
    ("210-555-0182", 6, "community", "Grandparent emergency scam, asks for a wire.", "Estafa de abuelos, pide un giro."),
]


async def seed(session: AsyncSession) -> None:
    await ensure_watchers(session)
    await ensure_flagged(session)
    existing = await session.get(Contact, MAYA_ID)
    if existing:
        return
    now = utcnow()
    contact = Contact(
        id=MAYA_ID,
        name="Maya",
        phone="210-555-0100",
        token=MAYA_TOKEN,
        created_at=now,
    )
    user = User(
        id=ROSA_ID,
        name="Rosa",
        phone="210-555-0199",
        language="en",
        trusted_contact_id=MAYA_ID,
        home_id="rosa",
        created_at=now,
    )
    session.add_all([contact, user])
    history = [
        ("Oak Apartments", 900, now - timedelta(days=3)),
        ("CPS Energy", 140, now - timedelta(days=2, hours=3)),
        ("H-E-B", 62, now - timedelta(days=1, hours=6)),
        ("Sofia", 50, now - timedelta(days=1, hours=1)),
        ("City Water", 48, now - timedelta(hours=20)),
    ]
    for recipient, amount, when in history:
        session.add(
            PaymentAttempt(
                id=str(uuid.uuid4()),
                created_at=when,
                user_id=ROSA_ID,
                amount=amount,
                recipient=recipient,
                method="ach",
                prompt_text="",
                status="seed",
                outcome="allow",
                stage=0,
                score=0,
            )
        )
    session.add(
        PaymentAttempt(
            id=str(uuid.uuid4()),
            created_at=now - timedelta(hours=6),
            user_id=ROSA_ID,
            amount=2000,
            recipient="IRS Collections",
            method="instant",
            prompt_text="Earlier practice hold.",
            status="denied",
            outcome="hold",
            stage=4,
            score=90,
        )
    )
    await session.commit()


async def ensure_flagged(session: AsyncSession) -> None:
    now = utcnow()
    for raw, reports, source, en, es in SEED_FLAGGED:
        number = reputation.normalize(raw)
        if not number or await session.get(FlaggedNumber, number) is not None:
            continue
        session.add(
            FlaggedNumber(
                number=number, reports=reports, source=source,
                reason_en=en, reason_es=es, first_seen=now, last_seen=now,
            )
        )
    await session.commit()


async def report_number(session: AsyncSession, number: str, source: str = "community", reason: str = "") -> dict:
    return await reputation.report(session, number, source=source or "community", reason_en=reason, reason_es=reason)


async def lookup_number(session: AsyncSession, number: str) -> dict:
    rep = await reputation.lookup(session, number)
    rep["enrichment"] = await reputation.enrich(number)
    return rep


async def ensure_watchers(session: AsyncSession) -> None:
    load_desks()
    for spec in DESKS:
        if await session.get(Watcher, spec["id"]) is not None:
            continue
        session.add(
            Watcher(
                id=spec["id"],
                name_en=spec["name_en"],
                name_es=spec["name_es"],
                signal=spec["signal"],
                phrases=dumps(list(spec["phrases"])),
                sentence_en=spec["sentence_en"],
                sentence_es=spec["sentence_es"],
                builtin=1,
            )
        )
    await session.commit()


async def list_watchers(session: AsyncSession, language: str) -> dict:
    rows = (await session.scalars(select(Watcher).order_by(Watcher.builtin.desc(), Watcher.name_en))).all()
    return {"watchers": [_watcher_public(row, language) for row in rows]}


async def add_watcher(session: AsyncSession, name: str, phrases: list[str], signal: str, sentence: str, language: str) -> dict:
    if signal not in MESSAGE_SIGNALS:
        raise ValueError("Choose a pattern the alarm already knows.")
    clean = []
    for phrase in phrases:
        item = phrase.strip().lower()
        if len(item) >= 3:
            clean.append(item[:80])
    if not clean or len(clean) > 12:
        raise ValueError("Add between 1 and 12 phrases, each at least 3 letters.")
    title = name.strip()[:60]
    if len(title) < 2:
        raise ValueError("Name the watcher.")
    note = sentence.strip()[:200] or title
    row = Watcher(
        id=uuid.uuid4().hex[:12],
        name_en=title,
        name_es=title,
        signal=signal,
        phrases=dumps(clean),
        sentence_en=note,
        sentence_es=note,
        builtin=0,
    )
    session.add(row)
    await session.commit()
    return _watcher_public(row, language)


def _watcher_public(row: Watcher, language: str) -> dict:
    spanish = language == "es"
    phrases = loads(row.phrases, [])
    return {
        "id": row.id,
        "name": row.name_es if spanish else row.name_en,
        "signal": row.signal,
        "phrases": phrases if isinstance(phrases, list) else [],
        "sentence": row.sentence_es if spanish else row.sentence_en,
        "builtin": bool(row.builtin),
    }


async def _watch(session: AsyncSession, text: str, signals: dict, language: str) -> tuple[dict, list[dict], dict[str, str]]:
    rows = (await session.scalars(select(Watcher))).all()
    watchers = []
    for row in rows:
        phrases = loads(row.phrases, [])
        watchers.append(
            {
                "id": row.id,
                "name_en": row.name_en,
                "name_es": row.name_es,
                "signal": row.signal,
                "phrases": phrases if isinstance(phrases, list) else [],
                "sentence_en": row.sentence_en,
                "sentence_es": row.sentence_es,
            }
        )
    signals, hits = apply_watchers(text, signals, watchers, language)
    overrides = {hit["signal"]: hit["sentence"] for hit in hits if hit["heat"] > 0}
    return signals, hits, overrides


async def setup_pair(
    session: AsyncSession,
    user_name: str,
    user_phone: str,
    contact_name: str,
    contact_phone: str,
    language: str,
) -> dict:
    now = utcnow()
    contact = Contact(
        id=str(uuid.uuid4()),
        name=contact_name.strip(),
        phone=contact_phone.strip(),
        token=uuid.uuid4().hex,
        created_at=now,
    )
    user = User(
        id=str(uuid.uuid4()),
        name=user_name.strip(),
        phone=user_phone.strip(),
        language=language,
        trusted_contact_id=contact.id,
        home_id=uuid.uuid4().hex[:12],
        created_at=now,
    )
    session.add_all([contact, user])
    await session.commit()
    return _session_payload(user, contact)


async def rosa_session(session: AsyncSession) -> dict:
    user = await _user(session, ROSA_ID)
    contact = await _contact_for_user(session, user)
    return _session_payload(user, contact)


def _session_payload(user: User, contact: Contact) -> dict:
    return {
        "user_id": user.id,
        "name": user.name,
        "phone": user.phone,
        "language": user.language,
        "contact_name": contact.name,
        "contact_phone": contact.phone,
        "crew_path": f"/crew/{contact.token}",
        "token": contact.token,
        "home_id": user.home_id,
    }


async def set_language(session: AsyncSession, user_id: str, language: str) -> dict:
    user = await _user(session, user_id)
    user.language = language
    await session.commit()
    contact = await _contact_for_user(session, user)
    return _session_payload(user, contact)


async def list_reasons(session: AsyncSession, language: str) -> dict:
    return {"reasons": await _ranked(session, language)}


async def check_payment(
    session: AsyncSession,
    user_id: str,
    amount: float,
    recipient: str,
    method: str,
    prompt_text: str | None,
    image_base64: str | None,
    on_call: bool,
    pressure_elevated: bool,
    why: str | None = None,
) -> dict:
    user = await _user(session, user_id)
    from app.redact import redact

    text = redact(prompt_text)
    image = decode_image(image_base64) if image_base64 else None
    labels = await label_message(text, image, user.language)
    known, amounts = await _history(session, user.id)
    signals = wallet_signals(amount, recipient, method, known, amounts)
    signals.update(labels.signals)
    if on_call:
        signals["on_call"] = True
    if pressure_elevated and await _pressure_counts(session, user.id):
        signals["pressure_elevated"] = True
    reader_heat = sum(POINTS[key] for key in MESSAGE_SIGNALS if signals.get(key))
    signals, watcher_hits, watcher_overrides = await _watch(session, text or "", signals, user.language)
    looked = [ledger_line(signals, user.language), reader_line(labels.source, user.language, reader_heat), *watcher_hits]
    rep = await reputation.lookup(session, recipient)
    number_override: dict[str, str] = {}
    if rep["flagged"]:
        signals["flagged_number"] = True
        line = reputation.reason_line(rep, user.language)
        number_override["flagged_number"] = line
        looked.append({
            "id": "lineup",
            "name": "La Ficha" if user.language == "es" else "The Line-up",
            "sentence": line,
            "signal": "flagged_number",
            "heat": POINTS["flagged_number"],
        })
    why_id = why if known_why(why) else None
    why_weight = 0
    why_sentence = ""
    if why_id:
        ranked = await _ranked(session, user.language)
        chosen = next(item for item in ranked if item["id"] == why_id)
        signals, why_weight = apply_why(signals, why_id, chosen["q"])
        if why_weight:
            why_sentence = reason_sentence(user.language, why_id, chosen["rank"], chosen["of"])
    overrides = {**labels.reasons, **watcher_overrides, **number_override}
    if why_sentence:
        overrides["stated_reason"] = why_sentence
        looked.append(reason_line(user.language, why_sentence, why_weight))
    weights = {"stated_reason": why_weight} if why_weight else None
    result = score_signals(signals, user.language, overrides, weights)
    status = {"allow": "allowed", "verify": "verifying", "hold": "held"}[result.outcome]
    attempt = PaymentAttempt(
        id=str(uuid.uuid4()),
        created_at=utcnow(),
        user_id=user.id,
        amount=amount,
        recipient=recipient.strip(),
        method=method,
        prompt_text=text,
        status=status,
        outcome=result.outcome,
        stage=result.stage,
        score=result.score,
    )
    session.add(attempt)
    stored_signals = {**result.signals, "_source": labels.source, "_looked": looked}
    if why_id:
        stored_signals["_why"] = why_id
        stored_signals["_why_weight"] = why_weight
        if why_sentence:
            stored_signals["_why_sentence"] = why_sentence
    session.add(_risk_row(attempt, result, stored_signals))
    approval = None
    if result.outcome == "hold":
        contact = await _contact_for_user(session, user)
        approval = _approval(attempt, contact)
        session.add(approval)
    await session.flush()
    if result.outcome == "allow" and why_id:
        await _observe(session, attempt.id, dispute=False)
    await session.commit()
    return await _body(session, attempt, result.reasons, labels.source, approval, user.language, result.signals)


async def check_message(
    session: AsyncSession,
    user_id: str,
    prompt_text: str | None,
    image_base64: str | None,
) -> dict:
    user = await _user(session, user_id)
    from app.redact import redact

    text = redact(prompt_text)
    image = decode_image(image_base64) if image_base64 else None
    labels = await label_message(text, image, user.language)
    signals = dict(labels.signals)
    reader_heat = sum(POINTS[key] for key in MESSAGE_SIGNALS if signals.get(key))
    signals, watcher_hits, watcher_overrides = await _watch(session, text or "", signals, user.language)
    looked = [reader_line(labels.source, user.language, reader_heat), *watcher_hits]
    overrides = {**labels.reasons, **watcher_overrides}
    weights = None
    suggested = None
    why_id = suggest(text or "")
    if why_id:
        ranked = await _ranked(session, user.language)
        chosen = next(item for item in ranked if item["id"] == why_id)
        signals, weight = apply_why(signals, why_id, chosen["q"])
        if weight:
            sentence = reason_sentence(user.language, why_id, chosen["rank"], chosen["of"])
            overrides["stated_reason"] = sentence
            weights = {"stated_reason": weight}
            looked.append(reason_line(user.language, sentence, weight))
        suggested = chosen
    result = score_signals(signals, user.language, overrides, weights)
    return {
        "score": result.score,
        "outcome": result.outcome,
        "stage": result.stage,
        "reasons": result.reasons,
        "signals": result.signals,
        "label_source": labels.source,
        "saved_payment": False,
        "suggested_why": suggested,
        "review_note": review_note(user.language),
        "looked": looked,
    }


async def apply_friction(
    session: AsyncSession,
    attempt_id: str,
    user_id: str,
    on_call: bool,
    told_to_keep_secret: bool,
) -> dict:
    attempt, user = await _owned_attempt(session, attempt_id, user_id)
    if attempt.status in {"approved", "denied", "cancelled", "expired", "allowed"}:
        raise PermissionError("This payment is already decided.")
    signals, source = await _latest_signals(session, attempt.id)
    raw = await _raw_signals(session, attempt.id)
    if on_call:
        signals["on_call"] = True
    if told_to_keep_secret:
        signals["secrecy"] = True
    why_id = raw.get("_why") if known_why(str(raw.get("_why") or "")) else None
    why_weight = int(raw.get("_why_weight") or 0)
    why_sentence = str(raw.get("_why_sentence") or "")
    overrides = {"stated_reason": why_sentence} if why_sentence else {}
    weights = {"stated_reason": why_weight} if signals.get("stated_reason") and why_weight else None
    result = score_signals(signals, user.language, overrides, weights)
    attempt.score = result.score
    attempt.outcome = result.outcome
    attempt.stage = result.stage
    attempt.status = {"allow": "allowed", "verify": "verifying", "hold": "held"}[result.outcome]
    stored = {**result.signals, "_source": source}
    if why_id:
        stored["_why"] = why_id
        stored["_why_weight"] = why_weight
        if why_sentence:
            stored["_why_sentence"] = why_sentence
    if isinstance(raw.get("_looked"), list):
        stored["_looked"] = raw["_looked"]
    session.add(_risk_row(attempt, result, stored))
    approval = await _pending_approval(session, attempt.id)
    if result.outcome == "hold" and approval is None:
        contact = await _contact_for_user(session, user)
        approval = _approval(attempt, contact)
        session.add(approval)
    await session.flush()
    if result.outcome == "allow":
        await _observe(session, attempt.id, dispute=False)
    await session.commit()
    return await _body(session, attempt, result.reasons, source, approval, user.language, result.signals)


async def ask_contact(session: AsyncSession, attempt_id: str, user_id: str) -> dict:
    attempt, user = await _owned_attempt(session, attempt_id, user_id)
    if attempt.outcome == "allow":
        raise PermissionError("This payment does not need a second person.")
    if attempt.status in {"cancelled", "denied", "expired", "approved"}:
        raise PermissionError("This payment is already decided.")
    approval = await _latest_approval(session, attempt.id)
    if approval is None or approval.status not in {"pending", "approved", "denied"}:
        contact = await _contact_for_user(session, user)
        approval = _approval(attempt, contact)
        session.add(approval)
        if attempt.outcome == "hold":
            attempt.status = "held"
        await session.commit()
    reasons, source = await _latest_reasons(session, attempt.id)
    signals, _source = await _latest_signals(session, attempt.id)
    return await _body(session, attempt, reasons, source, approval, user.language, signals)


async def continue_payment(session: AsyncSession, attempt_id: str, user_id: str) -> dict:
    attempt, user = await _owned_attempt(session, attempt_id, user_id)
    approval = await _pending_approval(session, attempt.id)
    if approval is not None:
        raise PermissionError("The trusted contact has the decision.")
    if not user_may_continue(attempt.outcome):
        raise PermissionError("A held payment stays held until the trusted contact decides.")
    if attempt.status != "verifying":
        raise PermissionError("This payment is already decided.")
    attempt.status = "allowed"
    await _observe(session, attempt.id, dispute=False)
    await session.commit()
    reasons, source = await _latest_reasons(session, attempt.id)
    signals, _source = await _latest_signals(session, attempt.id)
    return await _body(session, attempt, reasons, source, None, user.language, signals)


async def cancel_payment(session: AsyncSession, attempt_id: str, user_id: str) -> dict:
    attempt, user = await _owned_attempt(session, attempt_id, user_id)
    if attempt.status in {"approved", "denied", "cancelled"}:
        raise PermissionError("This payment is already decided.")
    attempt.status = "cancelled"
    approval = await _pending_approval(session, attempt.id)
    if approval is not None:
        approval.status = "cancelled"
        approval.decided_at = utcnow()
    await session.commit()
    reasons, source = await _latest_reasons(session, attempt.id)
    signals, _source = await _latest_signals(session, attempt.id)
    return await _body(session, attempt, reasons, source, approval, user.language, signals)


async def get_attempt(session: AsyncSession, attempt_id: str, user_id: str) -> dict:
    attempt, user = await _owned_attempt(session, attempt_id, user_id)
    approval = await _latest_approval(session, attempt.id)
    await _expire(session, approval, attempt)
    reasons, source = await _latest_reasons(session, attempt.id)
    signals, _source = await _latest_signals(session, attempt.id)
    return await _body(session, attempt, reasons, source, approval, user.language, signals)


async def crew_view(session: AsyncSession, token: str) -> dict:
    contact = await _contact_by_token(session, token)
    user = await _user_for_contact(session, contact.id)
    approval = await _newest_pending(session, contact.id)
    attempt = None
    if approval is not None:
        attempt = await _attempt_by_id(session, approval.attempt_id)
        await _expire(session, approval, attempt)
        if approval.status != "pending":
            approval = None
            attempt = None
    pending = None
    if approval is not None and attempt is not None:
        reasons, _source = await _latest_reasons(session, attempt.id)
        pending = _pending_body(user, attempt, approval, reasons)
    return {
        "contact_name": contact.name,
        "user_name": user.name,
        "user_phone": user.phone,
        "pending": pending,
    }


async def decide(session: AsyncSession, approval_id: str, token: str, decision: str) -> dict:
    approval = await session.get(ApprovalRequest, approval_id)
    if approval is None:
        raise LookupError("That request was not found.")
    contact = await _contact_by_token(session, token)
    if approval.contact_id != contact.id:
        raise PermissionError("Only the trusted contact can decide.")
    attempt = await _attempt_by_id(session, approval.attempt_id)
    await _expire(session, approval, attempt)
    if approval.status != "pending":
        raise PermissionError("This request is no longer waiting.")
    if decision not in {"approved", "denied"}:
        raise PermissionError("Choose approve or deny.")
    if decision == "approved" and attempt.outcome not in {"hold", "verify"}:
        raise PermissionError("There is nothing to release.")
    approval.status = decision
    approval.decided_at = utcnow()
    attempt.status = decision
    await _observe(session, attempt.id, dispute=decision == "denied")
    await session.commit()
    user = await _user(session, attempt.user_id)
    reasons, _source = await _latest_reasons(session, attempt.id)
    return _pending_body(user, attempt, approval, reasons)


async def history(session: AsyncSession, token: str) -> dict:
    contact = await _contact_by_token(session, token)
    user = await _user_for_contact(session, contact.id)
    rows = (
        await session.execute(
            select(PaymentAttempt)
            .where(PaymentAttempt.user_id == user.id, PaymentAttempt.status != "seed")
            .order_by(PaymentAttempt.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    items = []
    for attempt in rows:
        reasons, _source = await _latest_reasons(session, attempt.id)
        items.append(
            {
                "attempt_id": attempt.id,
                "amount": attempt.amount,
                "recipient": attempt.recipient,
                "method": attempt.method,
                "status": attempt.status,
                "outcome": attempt.outcome,
                "stage": attempt.stage,
                "score": attempt.score,
                "reasons": reasons[:3],
                "created_at": as_utc(attempt.created_at).isoformat(),
            }
        )
    return {"user_name": user.name, "items": items}


async def history_chart(session: AsyncSession, token: str) -> dict:
    contact = await _contact_by_token(session, token)
    user = await _user_for_contact(session, contact.id)
    tiger = await _tiger_ready(session)
    if tiger:
        result = await session.execute(
            text(
                """
                SELECT bucket, attempts, holds
                FROM attempts_hourly
                WHERE user_id = :user_id
                ORDER BY bucket
                """
            ),
            {"user_id": user.id},
        )
        buckets = [
            {
                "bucket": as_utc(row.bucket).isoformat() if isinstance(row.bucket, datetime) else str(row.bucket),
                "attempts": int(row.attempts),
                "holds": int(row.holds),
            }
            for row in result
        ]
        return {"tiger": True, "buckets": buckets}
    rows = (
        await session.execute(
            select(PaymentAttempt)
            .where(PaymentAttempt.user_id == user.id)
            .order_by(PaymentAttempt.created_at)
        )
    ).scalars().all()
    grouped: dict[str, dict[str, int]] = {}
    for attempt in rows:
        stamp = as_utc(attempt.created_at).replace(minute=0, second=0, microsecond=0)
        key = stamp.isoformat()
        bucket = grouped.setdefault(key, {"attempts": 0, "holds": 0})
        bucket["attempts"] += 1
        if attempt.outcome == "hold":
            bucket["holds"] += 1
    buckets = [
        {"bucket": key, "attempts": value["attempts"], "holds": value["holds"]}
        for key, value in grouped.items()
    ]
    return {"tiger": False, "buckets": buckets}


async def record_vitals(session: AsyncSession, user_id: str, pulse: float, breathing: float) -> dict:
    user = await _user(session, user_id)
    session.add(
        VitalsSample(
            id=str(uuid.uuid4()),
            created_at=utcnow(),
            user_id=user.id,
            pulse=pulse,
            breathing=breathing,
        )
    )
    await session.commit()
    return await vitals_status(session, user.id)


async def vitals_status(session: AsyncSession, user_id: str) -> dict:
    user = await _user(session, user_id)
    since = utcnow() - timedelta(minutes=2)
    rows = (
        await session.execute(
            select(VitalsSample)
            .where(VitalsSample.user_id == user.id, VitalsSample.created_at >= since)
            .order_by(VitalsSample.created_at)
        )
    ).scalars().all()
    samples = [(as_utc(row.created_at), row.pulse, row.breathing) for row in rows]
    ready, elevated = pressure_status(samples)
    latest = rows[-1] if rows else None
    return {
        "baseline_ready": ready,
        "pressure_elevated": elevated,
        "pulse": latest.pulse if latest else None,
        "breathing": latest.breathing if latest else None,
        "samples": len(rows),
    }


async def alarm_active(session: AsyncSession, home_id: str) -> dict:
    user = (
        await session.execute(select(User).where(User.home_id == home_id))
    ).scalar_one_or_none()
    if user is None or user.trusted_contact_id is None:
        return {"active": False, "home_id": home_id}
    approval = await _newest_pending(session, user.trusted_contact_id)
    if approval is None:
        return {"active": False, "home_id": home_id}
    attempt = await _attempt_by_id(session, approval.attempt_id)
    await _expire(session, approval, attempt)
    active = approval.status == "pending" and attempt.outcome == "hold" and attempt.status == "held"
    return {"active": active, "home_id": home_id}


async def _pressure_counts(session: AsyncSession, user_id: str) -> bool:
    status = await vitals_status(session, user_id)
    return bool(status["baseline_ready"] and status["pressure_elevated"])


async def _history(session: AsyncSession, user_id: str) -> tuple[set[str], list[float]]:
    rows = (
        await session.execute(
            select(PaymentAttempt.recipient, PaymentAttempt.amount).where(
                PaymentAttempt.user_id == user_id,
                PaymentAttempt.status.in_(HISTORY_STATUSES),
            )
        )
    ).all()
    known = {normalize_recipient(recipient) for recipient, _amount in rows}
    amounts = [float(amount) for _recipient, amount in rows]
    return known, amounts


def _risk_row(attempt: PaymentAttempt, result, signals: dict) -> RiskCheck:
    return RiskCheck(
        id=str(uuid.uuid4()),
        created_at=utcnow(),
        attempt_id=attempt.id,
        score=result.score,
        outcome=result.outcome,
        signals=dumps(signals),
        reasons=dumps(result.reasons),
        stage=result.stage,
    )


def _approval(attempt: PaymentAttempt, contact: Contact) -> ApprovalRequest:
    return ApprovalRequest(
        id=str(uuid.uuid4()),
        created_at=utcnow(),
        attempt_id=attempt.id,
        contact_id=contact.id,
        status="pending",
    )


async def _ranked(session: AsyncSession, language: str) -> list[dict]:
    rows = (await session.scalars(select(ReasonBelief))).all()
    counts = {row.reason_id: (row.successes, row.disputes) for row in rows}
    return rank_reasons(counts, "es" if language == "es" else "en")


async def _raw_signals(session: AsyncSession, attempt_id: str) -> dict:
    row = await _latest_risk(session, attempt_id)
    if row is None:
        return {}
    raw = loads(row.signals, {})
    return raw if isinstance(raw, dict) else {}


async def _observe(session: AsyncSession, attempt_id: str, dispute: bool) -> None:
    if await session.get(ReasonObservation, attempt_id) is not None:
        return
    raw = await _raw_signals(session, attempt_id)
    why_id = raw.get("_why")
    if not known_why(str(why_id or "")):
        return
    reason_id = str(why_id)
    belief = await session.get(ReasonBelief, reason_id)
    if belief is None:
        belief = ReasonBelief(reason_id=reason_id, successes=0, disputes=0)
        session.add(belief)
    if dispute:
        belief.disputes += 1
    else:
        belief.successes += 1
    session.add(ReasonObservation(attempt_id=attempt_id, reason_id=reason_id, target=1 if dispute else 0))


async def _why_view(session: AsyncSession, attempt_id: str, language: str) -> dict | None:
    raw = await _raw_signals(session, attempt_id)
    why_id = raw.get("_why")
    if not known_why(str(why_id or "")):
        return None
    return next(item for item in await _ranked(session, language) if item["id"] == why_id)


async def _body(
    session: AsyncSession,
    attempt: PaymentAttempt,
    reasons: list[str],
    source: str,
    approval: ApprovalRequest | None,
    language: str,
    signals: dict | None = None,
) -> dict:
    body = _check_body(attempt, reasons, source, approval, language, signals)
    body["why"] = await _why_view(session, attempt.id, language)
    raw = await _raw_signals(session, attempt.id)
    looked = raw.get("_looked")
    body["looked"] = looked if isinstance(looked, list) else []
    return body


def _check_body(
    attempt: PaymentAttempt,
    reasons: list[str],
    source: str,
    approval: ApprovalRequest | None,
    language: str,
    signals: dict | None = None,
) -> dict:
    visible = {key: bool((signals or {}).get(key)) for key in POINTS}
    return {
        "attempt_id": attempt.id,
        "amount": attempt.amount,
        "recipient": attempt.recipient,
        "method": attempt.method,
        "score": attempt.score,
        "outcome": attempt.outcome,
        "stage": attempt.stage,
        "reasons": reasons,
        "signals": visible,
        "status": attempt.status,
        "label_source": source,
        "approval_id": None if approval is None else approval.id,
        "approval_status": None if approval is None else approval.status,
        "warning": warning_for(language),
        "created_at": as_utc(attempt.created_at).isoformat(),
        "why": None,
    }


def _pending_body(user: User, attempt: PaymentAttempt, approval: ApprovalRequest, reasons: list[str]) -> dict:
    language = "es" if user.language == "es" else "en"
    method = METHOD_LABELS[language].get(attempt.method, attempt.method)
    amount = f"${attempt.amount:,.0f}"
    if language == "es":
        fact = f"{user.name} intentó enviar {amount} a {attempt.recipient} por {method}."
        empty = "No compartió un mensaje."
    else:
        fact = f"{user.name} tried to send {amount} to {attempt.recipient} by {method}."
        empty = "They did not share a message."
    report = attempt.prompt_text.strip() or empty
    inference = " ".join(reasons) if reasons else empty
    return {
        "approval_id": approval.id,
        "attempt_id": attempt.id,
        "status": approval.status,
        "fact": fact,
        "user_report": report,
        "inference": inference,
        "unknown": UNKNOWN[language],
        "action": ACTION[language],
        "amount": attempt.amount,
        "recipient": attempt.recipient,
        "score": attempt.score,
        "stage": attempt.stage,
        "reasons": reasons,
    }


async def _expire(session: AsyncSession, approval: ApprovalRequest | None, attempt: PaymentAttempt | None) -> None:
    if approval is None or approval.status != "pending":
        return
    age = utcnow() - as_utc(approval.created_at)
    if age <= timedelta(seconds=get_settings().hold_timeout_seconds):
        return
    approval.status = "expired"
    approval.decided_at = utcnow()
    if attempt is not None and attempt.status in {"held", "verifying"}:
        attempt.status = "expired"
    await session.commit()


async def _latest_signals(session: AsyncSession, attempt_id: str) -> tuple[dict, str]:
    row = await _latest_risk(session, attempt_id)
    if row is None:
        return {}, "none"
    raw = loads(row.signals, {})
    if not isinstance(raw, dict):
        return {}, "none"
    source = str(raw.get("_source") or "none")
    signals = {key: bool(raw.get(key)) for key in POINTS}
    return signals, source


async def _latest_reasons(session: AsyncSession, attempt_id: str) -> tuple[list[str], str]:
    row = await _latest_risk(session, attempt_id)
    if row is None:
        return [], "none"
    raw = loads(row.reasons, [])
    reasons = [str(item) for item in raw] if isinstance(raw, list) else []
    signals = loads(row.signals, {})
    source = "none"
    if isinstance(signals, dict):
        source = str(signals.get("_source") or "none")
    return reasons, source


async def _latest_risk(session: AsyncSession, attempt_id: str) -> RiskCheck | None:
    return (
        await session.execute(
            select(RiskCheck)
            .where(RiskCheck.attempt_id == attempt_id)
            .order_by(RiskCheck.created_at.desc())
        )
    ).scalars().first()


async def _pending_approval(session: AsyncSession, attempt_id: str) -> ApprovalRequest | None:
    return (
        await session.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.attempt_id == attempt_id,
                ApprovalRequest.status == "pending",
            )
        )
    ).scalars().first()


async def _latest_approval(session: AsyncSession, attempt_id: str) -> ApprovalRequest | None:
    return (
        await session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.attempt_id == attempt_id)
            .order_by(ApprovalRequest.created_at.desc())
        )
    ).scalars().first()


async def _newest_pending(session: AsyncSession, contact_id: str) -> ApprovalRequest | None:
    return (
        await session.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.contact_id == contact_id, ApprovalRequest.status == "pending")
            .order_by(ApprovalRequest.created_at.desc())
        )
    ).scalars().first()


async def _owned_attempt(session: AsyncSession, attempt_id: str, user_id: str) -> tuple[PaymentAttempt, User]:
    user = await _user(session, user_id)
    attempt = await _attempt_by_id(session, attempt_id)
    if attempt.user_id != user.id:
        raise PermissionError("That payment is not yours.")
    return attempt, user


async def _attempt_by_id(session: AsyncSession, attempt_id: str) -> PaymentAttempt:
    attempt = (
        await session.execute(select(PaymentAttempt).where(PaymentAttempt.id == attempt_id))
    ).scalars().first()
    if attempt is None:
        raise LookupError("That payment was not found.")
    return attempt


async def _user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise LookupError("That person was not found.")
    return user


async def _contact_for_user(session: AsyncSession, user: User) -> Contact:
    if not user.trusted_contact_id:
        raise LookupError("No trusted contact is set.")
    contact = await session.get(Contact, user.trusted_contact_id)
    if contact is None:
        raise LookupError("No trusted contact is set.")
    return contact


async def _contact_by_token(session: AsyncSession, token: str) -> Contact:
    contact = (
        await session.execute(select(Contact).where(Contact.token == token))
    ).scalar_one_or_none()
    if contact is None:
        raise LookupError("That crew link was not found.")
    return contact


async def _user_for_contact(session: AsyncSession, contact_id: str) -> User:
    user = (
        await session.execute(select(User).where(User.trusted_contact_id == contact_id))
    ).scalars().first()
    if user is None:
        raise LookupError("That crew link was not found.")
    return user


async def _tiger_ready(session: AsyncSession) -> bool:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    try:
        found = await session.execute(
            text(
                """
                SELECT 1 FROM timescaledb_information.continuous_aggregates
                WHERE view_name = 'attempts_hourly'
                """
            )
        )
        return found.first() is not None
    except Exception:
        return False


async def health(session: AsyncSession) -> dict:
    await session.execute(select(func.count()).select_from(User))
    settings = get_settings()
    return {
        "ok": True,
        "gemini": bool(settings.gemini_api_key),
        "elevenlabs": bool(settings.elevenlabs_api_key),
        "presage": bool(settings.presage_api_key),
        "tiger": await _tiger_ready(session),
    }
