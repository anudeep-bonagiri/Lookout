import re

SECRET = re.compile(
    r"(?i)\b(password|passcode|pin|one[- ]time(?: code)?|otp|verification code|security code|código(?: de verificación)?|clave)\b(?:\s*(?:is|:|#|-)\s*|\s+)([A-Za-z0-9]{4,12})"
)
CODE_IS = re.compile(r"(?i)\b(code|código)\s*(?:is|:)\s*(\d{4,8})")


def redact(text: str | None) -> str:
    if not text:
        return ""

    def hide(match: re.Match[str]) -> str:
        return f"{match.group(1)} [redacted]"

    cleaned = SECRET.sub(hide, text)
    return CODE_IS.sub(hide, cleaned)
