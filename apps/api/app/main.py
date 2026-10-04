from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import configure, init_db, session_factory
from app.labels import load_sample
from app.speech import synthesize
import app.service as service


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

    app = FastAPI(title="Scam Shield", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
        return HTTPException(status_code=500, detail="The alarm could not finish that step.")

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

    @app.get("/crew/{token}")
    async def crew(token: str, session: AsyncSession = Depends(db)):
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

    return app


def _method(method: str) -> None:
    if method not in {"ach", "instant", "wire", "gift_card", "crypto"}:
        raise HTTPException(status_code=400, detail="Choose a payment method.")


app = create_app()
