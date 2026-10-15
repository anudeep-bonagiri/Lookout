import hashlib
import hmac
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import configure, init_db, session_factory
from app.labels import load_sample
from app.speech import synthesize
import app.checkout as checkout
import app.paypal as paypal
import app.service as service
import app.voice as voice

# Routes that carry their own proof instead of the shared key: PayPal and
# ElevenLabs sign their webhooks, Twilio drives the voice line, health is public.
OPEN_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
    "/voice/incoming",
    "/voice/turn",
    "/voice/audio",
    "/voice/transcript",
    "/paypal/webhooks",
}
KEY_HEADER = "x-lookout-key"
ELEVENLABS_MAX_AGE = 30 * 60


class SetupIn(BaseModel):
    user_name: str = Field(min_length=1, max_length=80)
    user_phone: str = Field(min_length=7, max_length=40)
    contact_name: str = Field(min_length=1, max_length=80)
    contact_phone: str = Field(min_length=7, max_length=40)
    language: str = "en"


class LanguageIn(BaseModel):
    language: str


class CheckIn(BaseModel):
    user_id: str
    amount: float = Field(gt=0, lt=1_000_000)
    recipient: str = Field(min_length=1, max_length=80)
    method: str
    prompt_text: str | None = Field(default=None, max_length=4000)
    image_base64: str | None = None
    on_call: bool = False
    pressure_elevated: bool = False
    why: str | None = Field(default=None, max_length=40)


class WatcherIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    phrases: list[str] = Field(min_length=1, max_length=12)
    signal: str
    sentence: str = Field(default="", max_length=200)
    language: str = "en"


class MessageIn(BaseModel):
    user_id: str
    prompt_text: str | None = Field(default=None, max_length=4000)
    image_base64: str | None = None


class AttemptIn(BaseModel):
    user_id: str


class FrictionIn(BaseModel):
    user_id: str
    on_call: bool = False
    told_to_keep_secret: bool = False


class DecideIn(BaseModel):
    token: str
    decision: str


class ApprovalIn(BaseModel):
    user_id: str
    attempt_id: str


class SpeakIn(BaseModel):
    language: str = "en"


class VitalsIn(BaseModel):
    user_id: str
    pulse: float = Field(gt=20, lt=220)
    breathing: float = Field(gt=2, lt=60)


class ReportNumberIn(BaseModel):
    number: str = Field(min_length=3, max_length=40)
    source: str = "community"
    reason: str = Field(default="", max_length=200)


class CallMeIn(BaseModel):
    to: str = Field(min_length=7, max_length=40)


class PayPalOrderIn(BaseModel):
    user_id: str
    amount: float = Field(gt=0, lt=1_000_000)
    recipient: str = Field(min_length=1, max_length=80)
    payee_email: str = Field(default="", max_length=120)
    prompt_text: str | None = Field(default=None, max_length=4000)
    page_hash: str = Field(default="", max_length=64)
    source_url: str = Field(default="", max_length=500)
    currency: str = Field(default="", max_length=3)
    vault_id: str = Field(default="", max_length=80)
    store_in_vault: bool = False
    return_url: str = Field(default="", max_length=500)
    cancel_url: str = Field(default="", max_length=500)


class PayPalAuthorizeIn(BaseModel):
    user_id: str
    on_call: bool = False


def create_app(database_url: str | None = None) -> FastAPI:
    settings = get_settings()
    configure(database_url or settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await init_db()
        factory = session_factory()
        async with factory() as session:
            await service.seed(session)
        yield

    app = FastAPI(title="Lookout", lifespan=lifespan)
    origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Content-Type", KEY_HEADER],
        )

    @app.middleware("http")
    async def require_key(request: Request, call_next):
        key = get_settings().lookout_api_key
        if key and request.url.path not in OPEN_PATHS and request.method != "OPTIONS":
            sent = request.headers.get(KEY_HEADER, "")
            if not hmac.compare_digest(sent.encode(), key.encode()):
                return JSONResponse(status_code=401, content={"detail": "This API needs the Lookout key."})
        return await call_next(request)

    async def db() -> AsyncSession:
        factory = session_factory()
        async with factory() as session:
            yield session

    def fail(exc: Exception) -> HTTPException:
        if isinstance(exc, LookupError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, PermissionError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, ValueError):
            return HTTPException(status_code=400, detail=str(exc))
        if isinstance(exc, paypal.PayPalUnavailable):
            return HTTPException(status_code=503, detail=str(exc))
        if isinstance(exc, paypal.PayPalError):
            return HTTPException(status_code=502, detail=str(exc))
        return HTTPException(status_code=500, detail="The alarm could not finish that step.")

    PAYPAL_FAILURES = (LookupError, ValueError, PermissionError, paypal.PayPalUnavailable, paypal.PayPalError)

    @app.get("/health")
    async def health(session: AsyncSession = Depends(db)):
        return await service.health(session)

    @app.get("/demo/rosa")
    async def demo_rosa(session: AsyncSession = Depends(db)):
        return await service.rosa_session(session)

    @app.get("/samples/irs")
    async def irs_sample(language: str = "en"):
        lang = "es" if language == "es" else "en"
        return {"language": lang, "text": load_sample(lang)}

    @app.post("/setup")
    async def setup(body: SetupIn, session: AsyncSession = Depends(db)):
        if body.language not in {"en", "es"}:
            raise HTTPException(status_code=400, detail="Choose English or Spanish.")
        return await service.setup_pair(
            session,
            body.user_name,
            body.user_phone,
            body.contact_name,
            body.contact_phone,
            body.language,
        )

    @app.patch("/users/{user_id}/language")
    async def language(user_id: str, body: LanguageIn, session: AsyncSession = Depends(db)):
        if body.language not in {"en", "es"}:
            raise HTTPException(status_code=400, detail="Choose English or Spanish.")
        try:
            return await service.set_language(session, user_id, body.language)
        except LookupError as exc:
            raise fail(exc) from exc

    @app.get("/reasons")
    async def reasons(language: str = "en", session: AsyncSession = Depends(db)):
        lang = "es" if language == "es" else "en"
        return await service.list_reasons(session, lang)

    @app.get("/watchers")
    async def watchers(language: str = "en", session: AsyncSession = Depends(db)):
        lang = "es" if language == "es" else "en"
        return await service.list_watchers(session, lang)

    @app.post("/watchers")
    async def add_watcher(body: WatcherIn, session: AsyncSession = Depends(db)):
        lang = "es" if body.language == "es" else "en"
        try:
            return await service.add_watcher(session, body.name, body.phrases, body.signal, body.sentence, lang)
        except ValueError as exc:
            raise fail(exc) from exc

    @app.post("/check")
    async def check(body: CheckIn, session: AsyncSession = Depends(db)):
        _method(body.method)
        try:
            return await service.check_payment(
                session,
                body.user_id,
                body.amount,
                body.recipient,
                body.method,
                body.prompt_text,
                body.image_base64,
                body.on_call,
                body.pressure_elevated,
                body.why,
            )
        except (LookupError, ValueError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.post("/message-check")
    async def message_check(body: MessageIn, session: AsyncSession = Depends(db)):
        try:
            return await service.check_message(session, body.user_id, body.prompt_text, body.image_base64)
        except (LookupError, ValueError) as exc:
            raise fail(exc) from exc

    @app.post("/attempts/{attempt_id}/friction")
    async def friction(attempt_id: str, body: FrictionIn, session: AsyncSession = Depends(db)):
        try:
            return await service.apply_friction(
                session, attempt_id, body.user_id, body.on_call, body.told_to_keep_secret
            )
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.post("/attempts/{attempt_id}/ask")
    async def ask(attempt_id: str, body: AttemptIn, session: AsyncSession = Depends(db)):
        try:
            return await service.ask_contact(session, attempt_id, body.user_id)
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.post("/attempts/{attempt_id}/continue")
    async def continue_payment(attempt_id: str, body: AttemptIn, session: AsyncSession = Depends(db)):
        try:
            return await service.continue_payment(session, attempt_id, body.user_id)
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.post("/attempts/{attempt_id}/cancel")
    async def cancel(attempt_id: str, body: AttemptIn, session: AsyncSession = Depends(db)):
        try:
            return await service.cancel_payment(session, attempt_id, body.user_id)
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.get("/attempts/{attempt_id}")
    async def attempt(attempt_id: str, user_id: str, session: AsyncSession = Depends(db)):
        try:
            return await service.get_attempt(session, attempt_id, user_id)
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.post("/approvals")
    async def create_approval(body: ApprovalIn, session: AsyncSession = Depends(db)):
        try:
            return await service.ask_contact(session, body.attempt_id, body.user_id)
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.get("/trusted/{token}")
    async def trusted(token: str, session: AsyncSession = Depends(db)):
        try:
            return await service.crew_view(session, token)
        except LookupError as exc:
            raise fail(exc) from exc

    @app.post("/approvals/{approval_id}/decide")
    async def decide(approval_id: str, body: DecideIn, session: AsyncSession = Depends(db)):
        if body.decision not in {"approved", "denied"}:
            raise HTTPException(status_code=400, detail="Choose approve or deny.")
        try:
            return await service.decide(session, approval_id, body.token, body.decision)
        except (LookupError, PermissionError) as exc:
            raise fail(exc) from exc

    @app.get("/history")
    async def history(token: str, session: AsyncSession = Depends(db)):
        try:
            return await service.history(session, token)
        except LookupError as exc:
            raise fail(exc) from exc

    @app.get("/history/chart")
    async def chart(token: str, session: AsyncSession = Depends(db)):
        try:
            return await service.history_chart(session, token)
        except LookupError as exc:
            raise fail(exc) from exc

    @app.post("/speak")
    async def speak(body: SpeakIn):
        language = "es" if body.language == "es" else "en"
        try:
            audio, transcript = await synthesize(language)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="The spoken warning is unavailable.") from exc
        if audio is None:
            return {"fallback": True, "text": transcript, "language": language}
        return Response(content=audio, media_type="audio/mpeg")

    @app.post("/vitals")
    async def vitals(body: VitalsIn, session: AsyncSession = Depends(db)):
        try:
            return await service.record_vitals(session, body.user_id, body.pulse, body.breathing)
        except LookupError as exc:
            raise fail(exc) from exc

    @app.get("/vitals/status")
    async def vitals_status(user_id: str, session: AsyncSession = Depends(db)):
        try:
            return await service.vitals_status(session, user_id)
        except LookupError as exc:
            raise fail(exc) from exc

    @app.get("/alarms/active")
    async def alarms(home_id: str, session: AsyncSession = Depends(db)):
        return await service.alarm_active(session, home_id)

    @app.post("/voice/incoming")
    async def voice_incoming():
        return Response(content=voice.incoming_twiml(), media_type="application/xml")

    @app.post("/voice/turn")
    async def voice_turn(request: Request, step: int = 1, session: AsyncSession = Depends(db)):
        form = await request.form()
        call_sid = str(form.get("CallSid") or "demo")
        speech = str(form.get("SpeechResult") or "")
        from_number = str(form.get("From") or "")
        xml = await voice.turn_twiml(session, call_sid, speech, step, from_number)
        return Response(content=xml, media_type="application/xml")

    @app.get("/voice/audio")
    async def voice_audio(t: str):
        data = await voice.audio_for(t)
        if data is None:
            raise HTTPException(status_code=404, detail="No audio for that line.")
        return Response(content=data, media_type="audio/mpeg")

    @app.post("/voice/transcript")
    async def voice_transcript(request: Request, session: AsyncSession = Depends(db)):
        raw = await request.body()
        secret = get_settings().elevenlabs_webhook_secret
        if secret and not elevenlabs_signed(request.headers.get("elevenlabs-signature", ""), raw, secret):
            raise HTTPException(status_code=401, detail="That transcript was not signed by ElevenLabs.")
        try:
            import json

            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return await voice.ingest_transcript(session, payload)

    @app.get("/voice/transcripts")
    async def voice_transcripts(session: AsyncSession = Depends(db)):
        return await service.list_transcripts(session)

    @app.get("/numbers/{number}")
    async def number_lookup(number: str, session: AsyncSession = Depends(db)):
        return await service.lookup_number(session, number)

    @app.post("/numbers/report")
    async def number_report(body: ReportNumberIn, session: AsyncSession = Depends(db)):
        return await service.report_number(session, body.number, body.source, body.reason)

    @app.post("/voice/call")
    async def voice_call(body: CallMeIn, request: Request):
        import app.calls as calls

        return await calls.place_call(body.to, str(request.base_url))

    @app.post("/paypal/orders")
    async def paypal_create(body: PayPalOrderIn, session: AsyncSession = Depends(db)):
        try:
            return await checkout.create_order(
                session,
                body.user_id,
                body.amount,
                body.recipient,
                body.payee_email,
                body.prompt_text,
                body.page_hash,
                body.source_url,
                body.currency,
                body.vault_id,
                body.store_in_vault,
                body.return_url,
                body.cancel_url,
            )
        except PAYPAL_FAILURES as exc:
            raise fail(exc) from exc

    @app.post("/paypal/orders/{order_id}/authorize")
    async def paypal_authorize(order_id: str, body: PayPalAuthorizeIn, session: AsyncSession = Depends(db)):
        try:
            return await checkout.authorize(session, order_id, body.user_id, body.on_call)
        except PAYPAL_FAILURES as exc:
            raise fail(exc) from exc

    @app.get("/paypal/orders/{order_id}")
    async def paypal_order(order_id: str, user_id: str, session: AsyncSession = Depends(db)):
        try:
            return await checkout.view(session, order_id, user_id)
        except PAYPAL_FAILURES as exc:
            raise fail(exc) from exc

    @app.post("/paypal/webhooks")
    async def paypal_webhook(request: Request, session: AsyncSession = Depends(db)):
        raw = await request.body()
        ok = await paypal.verify_webhook(dict(request.headers), raw, get_settings().paypal_webhook_id)
        if not ok:
            raise HTTPException(status_code=400, detail="That event was not signed by PayPal.")
        try:
            import json

            event = json.loads(raw or b"{}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="That event is not JSON.") from exc
        if not isinstance(event, dict):
            raise HTTPException(status_code=400, detail="That event is not JSON.")
        return await checkout.apply_webhook(session, event)

    return app


def _method(method: str) -> None:
    if method not in {"ach", "instant", "wire", "gift_card", "crypto"}:
        raise HTTPException(status_code=400, detail="Choose a payment method.")


def elevenlabs_signed(header: str, body: bytes, secret: str) -> bool:
    """ElevenLabs sends `t=<unix>,v0=<hex hmac-sha256 of "<unix>.<body>">`."""
    parts = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
    stamp = parts.get("t", "")
    given = parts.get("v0", "")
    if not stamp.isdigit() or not given:
        return False
    if abs(time.time() - int(stamp)) > ELEVENLABS_MAX_AGE:
        return False
    expected = hmac.new(secret.encode(), f"{stamp}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)


app = create_app()
