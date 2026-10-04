"""A phone number you can call to check a scam.

Twilio points an incoming call at /voice/incoming. The caller says, in their
own words, what a caller or a text message told them. We run those words
through the same reader and scorer the wallet uses (app.labels + app.scoring),
ask one rehearsed follow-up, then give a plain verdict and hang up.

No Twilio SDK is needed: we return TwiML (XML) by hand. Call state is kept in
memory, keyed by Twilio's CallSid, which is enough for a single-process demo.
"""

import hashlib
import xml.sax.saxutils as sax

from sqlalchemy.ext.asyncio import AsyncSession

import app.reputation as reputation
from app.config import get_settings
from app.labels import generate_reply, label_message
from app.reasons import POINTS

# When an ElevenLabs key is set, lines are spoken by ElevenLabs via <Play>; the
# text for each line is kept here keyed by a short token, and /voice/audio reads
# it back. Without a key we fall straight back to Twilio's Polly voice.
LINES: dict[str, tuple[str, str]] = {}
AUDIO_CACHE: dict[str, bytes] = {}

# On a call there is no amount or method to weigh, only the words — plus whether
# the caller's number is already on the shared flag list. The verdict rides on
# those, with thresholds tuned for a call (a textbook scam clears 40).
CALL_SIGNALS = ("authority_claim", "threat_or_reward", "urgency", "secrecy", "sensitive_request", "on_call", "flagged_number")
SCAM_AT = 40
CAUTION_AT = 20

VOICE = "Polly.Joanna-Neural"
LANG = "en-US"

# Per-call memory: CallSid -> {text, signals, pending}
CALLS: dict[str, dict] = {}

AFFIRM = (
    "yes", "yeah", "yep", "yup", "sure", "correct", "they did", "he did",
    "she did", "they told", "uh huh", "that's right", "thats right",
    "sí", "si", "claro", "así es", "asi es",
)

GREETING = (
    "Hi, this is Lookout. I am a friend who double checks a payment before you send it. "
    "In your own words, tell me what the caller or the text message said. "
    "Take your time. I am listening."
)

HOLD_LINES = (
    "Okay. Please stop right here. What you are describing has the marks of a scam.",
    "A real agency will never threaten you with arrest, and will never ask for gift cards, a wire, or a code over the phone.",
    "Hang up now, and do not send anything. If you want to be sure, look the company up yourself and call the number on their real website. You did the right thing by checking first.",
)
VERIFY_LINES = (
    "This has a few of the warning signs I listen for.",
    "Before you send money to anyone, check with someone you trust, and never pay an official bill with gift cards or a wire.",
    "When in doubt, slow down. A real bill can wait ten minutes.",
)
ALLOW_LINES = (
    "I do not hear the usual scam signs in what you told me.",
    "Still, keep your guard up. If anyone rushes you, or tells you to keep a payment secret, that is your sign to stop and check.",
)


def _token(text: str, lang: str) -> str:
    key = hashlib.sha1(f"{lang}:{text}".encode()).hexdigest()[:12]
    LINES[key] = (text, lang)
    return key


def _say(text: str, lang: str = "en") -> str:
    """Speak a line: ElevenLabs via <Play> when a key is set, else Polly."""
    if get_settings().elevenlabs_api_key:
        return f"<Play>/voice/audio?t={_token(text, lang)}</Play>"
    return f'<Say voice="{VOICE}" language="{LANG}">{sax.escape(text)}</Say>'


async def audio_for(token: str) -> bytes | None:
    if token in AUDIO_CACHE:
        return AUDIO_CACHE[token]
    entry = LINES.get(token)
    if not entry:
        return None
    from app.speech import synthesize_text

    text, lang = entry
    data = await synthesize_text(text, lang)
    if data:
        AUDIO_CACHE[token] = data
    return data


def _gather(prompt: str, action: str) -> str:
    return (
        f'<Gather input="speech" action="{action}" method="POST" '
        f'speechTimeout="auto" language="{LANG}">{_say(prompt)}</Gather>'
    )


def _resp(*parts: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(parts) + "</Response>"


def incoming_twiml() -> str:
    return _resp(
        _gather(GREETING, "/voice/turn?step=1"),
        _say("I did not catch that. Call back any time, and I will be here."),
    )


def _affirmed(text: str) -> bool:
    low = f" {text.strip().lower()} "
    return any(f" {word} " in low or low.strip().startswith(word) for word in AFFIRM)


def _probe(signals: dict) -> tuple[str, str]:
    """Pick one natural yes/no question that, if answered yes, confirms a signal."""
    if not signals.get("secrecy"):
        return "secrecy", "One more thing. Did they tell you to keep this between us, and not tell your family or your bank?"
    if not signals.get("urgency"):
        return "urgency", "Did they say it has to be done right now, today, or something bad would happen?"
    if not signals.get("sensitive_request"):
        return "sensitive_request", "Did they ask you to pay with gift cards, a wire transfer, or a code from your phone?"
    if not signals.get("authority_claim"):
        return "authority_claim", "Did the person say they were from the government, your bank, or tech support?"
    return "on_call", "And are you still on the phone with that person right now?"


def call_score(signals: dict) -> int:
    return sum(POINTS[key] for key in CALL_SIGNALS if signals.get(key))


def _verdict(signals: dict) -> tuple[str, ...]:
    score = call_score(signals)
    if score >= SCAM_AT:
        return HOLD_LINES
    if score >= CAUTION_AT:
        return VERIFY_LINES
    return ALLOW_LINES


async def turn_twiml(session: AsyncSession, call_sid: str, speech: str, step: int, from_number: str = "") -> str:
    state = CALLS.setdefault(call_sid, {"text": "", "signals": {}, "pending": None, "from": from_number})
    if from_number and not state.get("from"):
        state["from"] = from_number

    # Look the caller's number up against the shared flag list, once per call.
    if "rep" not in state:
        rep = await reputation.lookup(session, state.get("from") or "")
        state["rep"] = rep
        if rep["flagged"]:
            state["signals"]["flagged_number"] = True

    # A yes to the previous follow-up confirms the signal it was probing for.
    pending = state.get("pending")
    if pending and speech and _affirmed(speech):
        state["signals"][pending] = True
    state["pending"] = None

    if speech:
        state["text"] = (state["text"] + " " + speech).strip()

    labels = await label_message(state["text"], None, "en")
    signals = {**labels.signals, **state["signals"]}
    state["signals"] = {key: bool(value) for key, value in signals.items()}

    fired = [key for key in CALL_SIGNALS if signals.get(key)]

    if step < 2:
        target, scripted = _probe(signals)
        state["pending"] = target
        prompt = await generate_reply(state["text"], fired, f"probe:{target}", "en") or scripted
        return _resp(
            _gather(prompt, "/voice/turn?step=2"),
            _say("Take your time. Tell me when you are ready."),
        )

    score = call_score(signals)
    level = "scam" if score >= SCAM_AT else "caution" if score >= CAUTION_AT else "clear"
    spoken = await generate_reply(state["text"], fired, f"verdict:{level}", "en")
    lines = [spoken] if spoken else list(_verdict(signals))
    rep = state.get("rep") or {}
    if rep.get("flagged"):
        lines = [reputation.reason_line(rep, "en")] + lines

    # Growing the shared list: a scam verdict reports the caller's number so the
    # next person who gets a call from it is already warned.
    if score >= SCAM_AT and state.get("from"):
        await reputation.report(
            session, state["from"], source="community",
            reason_en="Reported by a Lookout call check.",
            reason_es="Reportado por una verificación de Lookout.",
        )

    CALLS.pop(call_sid, None)
    return _resp(*[_say(line) for line in lines], "<Hangup/>")
