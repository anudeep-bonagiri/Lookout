from dataclasses import dataclass

from app.reasons import POINTS, reason_for

IRREVERSIBLE = {"instant", "wire", "gift_card", "crypto"}


@dataclass
class ScoreResult:
    score: int
    outcome: str
    stage: int
    reasons: list[str]
    signals: dict[str, bool]


def wallet_signals(
    amount: float,
    recipient: str,
    method: str,
    known_recipients: set[str],
    history_amounts: list[float],
) -> dict[str, bool]:
    name = recipient.strip().lower()
    if amount > 200 and history_amounts:
        unusual = amount > max(history_amounts) * 1.5
    elif amount > 200:
        unusual = True
    else:
        unusual = False
    return {
        "new_recipient": name not in known_recipients,
        "unusual_amount": unusual,
        "irreversible_method": method in IRREVERSIBLE,
    }


def stage_for(signals: dict[str, bool]) -> int:
    stage = 0
    if signals.get("authority_claim"):
        stage = 1
    if signals.get("threat_or_reward"):
        stage = max(stage, 2)
    if signals.get("urgency") or signals.get("secrecy"):
        stage = max(stage, 3)
    money_demand = signals.get("unusual_amount") or signals.get("sensitive_request")
    if signals.get("irreversible_method") or (signals.get("new_recipient") and money_demand):
        stage = max(stage, 4)
    return stage


def outcome_for(score: int) -> str:
    if score <= 39:
        return "allow"
    if score <= 69:
        return "verify"
    return "hold"


def score_signals(
    signals: dict[str, bool],
    language: str = "en",
    reason_overrides: dict[str, str] | None = None,
    weights: dict[str, int] | None = None,
) -> ScoreResult:
    overrides = reason_overrides or {}
    table = dict(POINTS)
    for key, value in (weights or {}).items():
        if key in table:
            table[key] = max(0, min(POINTS[key], int(value)))
    fired = [key for key in table if signals.get(key)]
    fired.sort(key=lambda key: (-table[key], key))
    total = min(100, sum(table[key] for key in fired))
    reasons = [reason_for(key, language, overrides.get(key)) for key in fired]
    clean = {key: bool(signals.get(key)) for key in POINTS}
    return ScoreResult(
        score=total,
        outcome=outcome_for(total),
        stage=stage_for(clean),
        reasons=reasons,
        signals=clean,
    )


def user_may_continue(outcome: str) -> bool:
    return outcome == "verify"


def contact_may_release(outcome: str, decision: str | None) -> bool:
    if outcome not in {"hold", "verify"}:
        return False
    return decision == "approved"
