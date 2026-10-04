import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.reasons import reason_for
from app.why import EMERGENCY_CUES

log = logging.getLogger("lookout")

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
    "fraud department",
    "fraud prevention",
    "bank fraud",
    "amazon security",
    "medicare",
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
    "dont tell",
    "keep this secret",
    "keep it secret",
    "keep it between us",
    "between us",
    "tell no one",
    "no le diga",
    "no le digas",
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
    "wire transfer",
    "wire the",
    "send a wire",
    "by wire",
    "zelle",
    "western union",
    "moneygram",
    "money gram",
    "tarjeta de regalo",
    "código de verificación",
    "codigo de verificacion",
    "giro bancario",
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
        "urgency": _hit(haystack, URGENCY) or _hit(haystack, EMERGENCY_CUES),
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


SIGNAL_PHRASES = {
    "authority_claim": "the caller claimed to be from the government, a bank, or tech support",
    "threat_or_reward": "the caller threatened arrest or dangled a prize",
    "urgency": "the caller rushed them to pay right away",
    "secrecy": "the caller told them to keep it secret",
    "sensitive_request": "the caller asked for gift cards, a wire, or a code",
    "on_call": "they are still on the phone with that person",
    "flagged_number": "the number has already been reported by other people",
}


async def generate_reply(transcript: str, detected: list[str], intent: str, language: str = "en") -> str | None:
    """NLP-written spoken reply for the call bot, conditioned on what the caller
    actually said and the verdict the rules engine already reached. Returns None
    with no Gemini key or on any error, so the caller falls back to scripted lines.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        return None
    language_name = "Spanish" if language == "es" else "English"
    heard = "; ".join(SIGNAL_PHRASES.get(key, key) for key in detected) or "nothing specific yet"
    base = (
        "You are Lookout, a warm, calm helper on a phone call with an older adult who is "
        "worried someone is scamming them. Speak plainly, like a kind person on the phone. "
        f"Reply in {language_name}. Rules you must follow: 2 to 3 short spoken sentences; "
        "no markdown, lists, or emoji; never say a named individual is a criminal; "
        "never ask for money, codes, card numbers, or personal information. "
        f"\n\nWhat the caller told you: \"\"\"{transcript or '(nothing yet)'}\"\"\"\n"
        f"Warning signs our check already found: {heard}.\n\n"
    )
    if intent.startswith("probe:"):
        target = intent.split(":", 1)[1]
        want = SIGNAL_PHRASES.get(target, target)
        task = (
            f"Ask ONE short, natural yes-or-no question to find out whether {want}. "
            "Reference what they said if it feels natural. One sentence only."
        )
    elif intent == "verdict:scam":
        task = (
            "Our fraud check decided this is LIKELY A SCAM. Gently tell them to stop and not send "
            "any money, name the specific warning sign(s) you heard in their words, and tell them to "
            "hang up and call the company back using the number on the company's official website, not "
            "the number they were given."
        )
    elif intent == "verdict:caution":
        task = (
            "Our check found some warning signs but is not certain. Tell them what gave you pause, say "
            "to check with someone they trust before sending money, and to never pay an official bill "
            "with gift cards or a wire."
        )
    else:
        task = (
            "Our check did not find the usual scam signs. Reassure them briefly, but remind them that if "
            "anyone rushes them or tells them to keep a payment secret, that is their cue to stop and check."
        )
    prompt = base + task + "\n\nRespond with only the words to speak."

    def call() -> str:
        import re as _re

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt],
            config=types.GenerateContentConfig(temperature=0.4),
        )
        said = (getattr(response, "text", None) or "").strip()
        said = _re.sub(r"[*_#`]+", "", said)  # strip stray markdown
        return " ".join(said.split())

    import asyncio

    try:
        said = await asyncio.to_thread(call)
    except Exception:
        log.exception("Voice reply generation failed. Using scripted lines.")
        return None
    return said or None


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
        "Read the message or the call words a person was given before sending money. "
        "A plea that someone is at a doctor, hospital, jail, or accident and needs money now is urgency. "
        "A request to hide it from family is secrecy. "
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
