POINTS: dict[str, int] = {
    "new_recipient": 15,
    "unusual_amount": 10,
    "irreversible_method": 15,
    "authority_claim": 10,
    "threat_or_reward": 15,
    "urgency": 10,
    "secrecy": 15,
    "sensitive_request": 15,
    "on_call": 10,
    "pressure_elevated": 10,
}

REASONS: dict[str, dict[str, str]] = {
    "en": {
        "new_recipient": "This recipient is not someone you have paid before.",
        "unusual_amount": "This amount is far above what you usually send.",
        "irreversible_method": "This kind of payment is very hard to undo.",
        "authority_claim": "Someone you do not know is claiming to be an official.",
        "threat_or_reward": "Real agencies do not threaten arrest by text or phone.",
        "urgency": "You are being rushed. That is how scams work.",
        "secrecy": "You are being told to keep this secret. That is how scams work.",
        "sensitive_request": "They are asking for gift cards, codes, or remote access.",
        "on_call": "You said you are on the phone with them right now.",
        "pressure_elevated": "Your pulse or breathing is higher than a moment ago.",
    },
    "es": {
        "new_recipient": "Esta persona no es alguien a quien usted le haya pagado antes.",
        "unusual_amount": "Esta cantidad está muy por encima de lo que usted suele enviar.",
        "irreversible_method": "Este tipo de pago es muy difícil de deshacer.",
        "authority_claim": "Alguien que usted no conoce dice ser un funcionario.",
        "threat_or_reward": "Las oficinas de verdad no amenazan con arresto por texto o por teléfono.",
        "urgency": "Le están apurando. Así funcionan las estafas.",
        "secrecy": "Le están pidiendo que lo mantenga en secreto. Así funcionan las estafas.",
        "sensitive_request": "Le piden tarjetas de regalo, códigos o acceso remoto.",
        "on_call": "Usted dijo que está al teléfono con ellos ahora mismo.",
        "pressure_elevated": "Su pulso o su respiración está más alto que hace un momento.",
    },
}

WARNINGS: dict[str, str] = {
    "en": "Stop. This payment is on hold. It looks like a scam. Let's check with someone you trust before any money moves.",
    "es": "Alto. Este pago está detenido. Parece una estafa. Vamos a preguntarle a alguien de su confianza antes de que salga el dinero.",
}

UNKNOWN: dict[str, str] = {
    "en": "The app cannot tell who is really on the other end.",
    "es": "La aplicación no puede saber quién está realmente del otro lado.",
}

ACTION: dict[str, str] = {
    "en": "Approve, deny, or call them.",
    "es": "Apruebe, rechace, o llámele.",
}

METHOD_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "ach": "bank transfer",
        "instant": "instant transfer",
        "wire": "wire",
        "gift_card": "gift card",
        "crypto": "crypto",
    },
    "es": {
        "ach": "transferencia bancaria",
        "instant": "transferencia instantánea",
        "wire": "giro",
        "gift_card": "tarjeta de regalo",
        "crypto": "criptomoneda",
    },
}


def reason_for(signal: str, language: str, override: str | None = None) -> str:
    if override and override.strip():
        return override.strip()
    pack = REASONS["es" if language == "es" else "en"]
    return pack[signal]


def warning_for(language: str) -> str:
    return WARNINGS["es" if language == "es" else "en"]
