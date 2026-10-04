"""Threat of a stated reason, updated from finished payments and disputes.

The payment action is not explored. Allow, verify, and hold stay a fixed
threshold on the signals. What moves is Q(reason): how threatening that
answer has been. One step, no discount, because the label arrives once:

    Q <- Q + (1 / (k + n + 1)) * (target - Q)

target is 1 when the trusted contact denies the payment and 0 when it
finishes. k is the prior strength, so one dispute cannot wipe the prior.
The same update is the mean of a Beta count: disputes over prior plus
observations. A reason adds heat only while Q stays at or above 0.40,
and that heat is capped at the existing per-signal maximum.
"""

from app.reasons import POINTS

PRIOR_STRENGTH = 4
FLOOR = 0.40

REASONS: list[dict] = [
    {
        "id": "threat",
        "prior": 0.90,
        "signals": ["threat_or_reward"],
        "en": "They threatened me if I do not pay.",
        "es": "Me amenazaron si no pago.",
    },
    {
        "id": "emergency",
        "prior": 0.88,
        "signals": ["urgency"],
        "en": "They say they are at a doctor, in jail, or in an accident and need the money now.",
        "es": "Dicen que están en el médico, en la cárcel o en un accidente y necesitan el dinero ahora.",
    },
    {
        "id": "gift",
        "prior": 0.86,
        "signals": ["sensitive_request"],
        "en": "They want a gift card, crypto, or a code.",
        "es": "Quieren una tarjeta de regalo, cripto o un código.",
    },
    {
        "id": "secret",
        "prior": 0.84,
        "signals": ["secrecy"],
        "en": "They told me to keep it secret.",
        "es": "Me dijeron que lo mantuviera en secreto.",
    },
    {
        "id": "official",
        "prior": 0.70,
        "signals": ["authority_claim"],
        "en": "An official told me I owe this.",
        "es": "Un funcionario me dijo que debo esto.",
    },
    {
        "id": "phone",
        "prior": 0.58,
        "signals": ["on_call"],
        "en": "I am on the phone with them.",
        "es": "Estoy al teléfono con esa persona.",
    },
    {
        "id": "new_person",
        "prior": 0.50,
        "signals": [],
        "en": "Someone I have not paid before.",
        "es": "Alguien a quien no le he pagado antes.",
    },
    {
        "id": "family",
        "prior": 0.14,
        "signals": [],
        "en": "Rent or a person I know.",
        "es": "Renta o una persona que conozco.",
    },
    {
        "id": "bill",
        "prior": 0.08,
        "signals": [],
        "en": "A bill I already pay.",
        "es": "Una factura que ya pago.",
    },
]

BY_ID = {item["id"]: item for item in REASONS}

EMERGENCY_CUES = (
    "at the doctor",
    "at the hospital",
    "in the hospital",
    "emergency room",
    "car accident",
    "been in an accident",
    "need bail",
    "bail me",
    "en el doctor",
    "en el hospital",
    "en el medico",
    "en el médico",
    "accidente",
    "la fianza",
    "estoy detenid",
)

CUES: dict[str, tuple[str, ...]] = {
    "emergency": EMERGENCY_CUES,
    "threat": ("arrest", "warrant", "jail", "arresto", "cárcel", "carcel"),
    "gift": ("gift card", "gift cards", "bitcoin", "crypto", "verification code", "tarjeta de regalo"),
    "secret": ("do not tell", "don't tell", "dont tell", "keep this secret", "no le diga", "no le digas", "no se lo cuente"),
    "official": ("irs", "social security", "this is the police", "hacienda", "seguro social"),
    "bill": ("electric bill", "water bill", "utility bill", "factura de la luz"),
}


def known(reason_id: str | None) -> bool:
    return reason_id in BY_ID


def suggest(text: str) -> str | None:
    haystack = text.lower()
    found = [reason_id for reason_id, cues in CUES.items() if any(cue in haystack for cue in cues)]
    if not found:
        return None
    return max(found, key=lambda reason_id: BY_ID[reason_id]["prior"])


def review_note(language: str) -> str:
    if language == "es":
        return "El revisor leyó solo las palabras que usted compartió. No entró a la llamada ni grabó la línea."
    return "The reviewer read only the words you shared. It did not join the call or record the line."


def posterior(prior: float, successes: int, disputes: int) -> float:
    total = PRIOR_STRENGTH + successes + disputes
    return (prior * PRIOR_STRENGTH + disputes) / total


def level(q: float) -> str:
    if q >= 0.66:
        return "high"
    if q >= FLOOR:
        return "mid"
    return "low"


def weight_for(q: float) -> int:
    if q < FLOOR:
        return 0
    return max(1, min(15, round(15 * q)))


def contribution(reason_id: str, q: float) -> int:
    if q < FLOOR:
        return 0
    spec = BY_ID[reason_id]
    return sum(POINTS[key] for key in spec["signals"]) + weight_for(q)


def apply(signals: dict[str, bool], reason_id: str | None, q: float) -> tuple[dict[str, bool], int]:
    if not known(reason_id) or q < FLOOR:
        return signals, 0
    out = dict(signals)
    for key in BY_ID[reason_id]["signals"]:
        out[key] = True
    out["stated_reason"] = True
    weight = weight_for(q)
    return out, weight


def label(reason_id: str, language: str) -> str:
    spec = BY_ID[reason_id]
    return spec["es"] if language == "es" else spec["en"]


def reason_sentence(language: str, reason_id: str, rank: int, total: int) -> str:
    text = label(reason_id, language)
    if language == "es":
        return f"Usted dijo que esta es la razón: {text} Esa razón ocupa el puesto {rank} de {total} por amenaza."
    return f"You said this is why: {text} That reason ranks {rank} of {total} for threat."


def rank(counts: dict[str, tuple[int, int]], language: str = "en") -> list[dict]:
    rows = []
    for spec in REASONS:
        successes, disputes = counts.get(spec["id"], (0, 0))
        q = posterior(spec["prior"], successes, disputes)
        rows.append(
            {
                "id": spec["id"],
                "label": label(spec["id"], language),
                "q": round(q, 4),
                "level": level(q),
                "points": contribution(spec["id"], q),
                "successes": successes,
                "disputes": disputes,
            }
        )
    rows.sort(key=lambda item: (-item["q"], item["id"]))
    total = len(rows)
    for index, item in enumerate(rows, start=1):
        item["rank"] = index
        item["of"] = total
    return rows
