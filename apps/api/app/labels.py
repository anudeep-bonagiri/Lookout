import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.reasons import reason_for

log = logging.getLogger("scamshield")

MESSAGE_SIGNALS = (
    "authority_claim",
    "threat_or_reward",
    "urgency",
    "secrecy",
    "sensitive_request",
)

AUTHORITY = (
    "irs",
    "internal revenue",
    "this is the police",
    "social security",
    "tech support",
    "microsoft support",
    "apple support",
    "department of the treasury",
    "seguro social",
    "soporte técnico",
    "soporte tecnico",
    "hacienda",
)
THREAT = (
    "arrest",
    "warrant",
    "frozen",
    "jail",
    "you have won",
    "prize",
    "arresto",
    "congelad",
    "premio",
    "cárcel",
    "carcel",
)
URGENCY = (
    "act now",
    "right now",
    "immediately",
    "stay on the line",
    "do not hang up",
    "don't hang up",
    "within the hour",
    "hoy mismo",
    "ahora mismo",
    "inmediatamente",
    "no cuelgue",
    "no cuelgues",
)
SECRECY = (
    "do not tell",
    "don't tell",
    "keep this secret",
    "tell no one",
    "no le diga",
    "no le cuente",
    "que no se entere",
    "no se lo cuente",
)
SENSITIVE = (
    "gift card",
    "gift cards",
    "bitcoin",
    "crypto",
    "remote access",
    "anydesk",
    "verification code",
    "one-time code",
    "tarjeta de regalo",
    "código de verificación",
    "codigo de verificacion",
)


@dataclass
class LabelResult:
    signals: dict[str, bool]
    reasons: dict[str, str]
    source: str


def label_heuristic(text: str, language: str) -> LabelResult:
    haystack = text.lower()
    flags = {
        "authority_claim": _hit(haystack, AUTHORITY),
        "threat_or_reward": _hit(haystack, THREAT),
        "urgency": _hit(haystack, URGENCY),
        "secrecy": _hit(haystack, SECRECY),
        "sensitive_request": _hit(haystack, SENSITIVE),
    }
    reasons = {key: reason_for(key, language) for key, on in flags.items() if on}
    return LabelResult(signals=flags, reasons=reasons, source="fallback")


def _hit(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


async def label_message(text: str, image: tuple[bytes, str] | None, language: str) -> LabelResult:
    settings = get_settings()
    if settings.gemini_api_key and (text.strip() or image):
        try:
            return await _label_gemini(text, image, language, settings.gemini_api_key, settings.gemini_model)
        except Exception:
            log.exception("Gemini labeling failed. Using offline rules.")
    if text.strip():
        return label_heuristic(text, language)
    return LabelResult(signals={key: False for key in MESSAGE_SIGNALS}, reasons={}, source="none")


async def _label_gemini(
    text: str,
    image: tuple[bytes, str] | None,
    language: str,
    api_key: str,
    model: str,
) -> LabelResult:
    import asyncio

    from google import genai
    from google.genai import types

    language_name = "Spanish" if language == "es" else "English"
    prompt = (
        "Read the message a person was given before sending money. "
        "Label only these patterns. Do not give a score. "
        f"Write any reason in {language_name}, in one short plain sentence. "
        "Describe the pattern. Do not say a named person is a criminal. "
        "If a flag is false, leave its reason empty.\n\n"
        f"Message:\n{text or '(no text, image only)'}"
    )
    parts: list[object] = [prompt]
    if image:
        blob, mime = image
        parts.append(types.Part.from_bytes(data=blob, mime_type=mime))

    def call() -> LabelResult:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=parts,
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_schema=_schema(),
            ),
        )
        payload = _payload(response)
        signals = {key: bool(payload.get(key)) for key in MESSAGE_SIGNALS}
        reasons = {}
        for key in MESSAGE_SIGNALS:
            sentence = str(payload.get(f"{key}_reason") or "").strip()
            if signals[key]:
                reasons[key] = sentence or reason_for(key, language)
        return LabelResult(signals=signals, reasons=reasons, source="gemini")

    return await asyncio.to_thread(call)


def _schema() -> dict:
    properties = {}
    for key in MESSAGE_SIGNALS:
        properties[key] = {"type": "boolean"}
        properties[f"{key}_reason"] = {"type": "string"}
    return {"type": "object", "properties": properties, "required": list(properties)}


def _payload(response: object) -> dict:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    if parsed is not None and hasattr(parsed, "model_dump"):
        return parsed.model_dump()
    text = getattr(response, "text", None) or ""
    if not text:
        raise ValueError("Gemini returned an empty label")
    return json.loads(text)


def load_sample(language: str) -> str:
    name = "irs_es.txt" if language == "es" else "irs_en.txt"
    path = Path(__file__).resolve().parent / "samples" / name
    return path.read_text(encoding="utf-8").strip()


def decode_image(data: str) -> tuple[bytes, str]:
    mime = "image/jpeg"
    raw = data.strip()
    if raw.startswith("data:"):
        header, raw = raw.split(",", 1)
        mime = header.split(";")[0].removeprefix("data:") or mime
    if mime not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("Use a JPEG, PNG, or WebP image.")
    if len(raw) > 6_000_000:
        raise ValueError("That image is too large.")
    try:
        blob = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError("That image could not be read.") from exc
    if len(blob) > 4_000_000:
        raise ValueError("That image is too large.")
    return blob, mime


def normalize_recipient(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()
