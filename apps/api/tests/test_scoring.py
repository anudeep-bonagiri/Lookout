import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.labels import label_heuristic, load_sample
from app.pressure import pressure_status
from app.reasons import POINTS
from app.redact import redact
from app.scoring import contact_may_release, score_signals, user_may_continue, wallet_signals

FIXTURES = Path(__file__).parent / "fixtures" / "payments.json"


def load_fixtures() -> list[dict]:
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    if not data:
        raise AssertionError("scoring fixtures are required")
    return data


def test_fixtures_cover_the_demo():
    fixtures = load_fixtures()
    assert sum(1 for item in fixtures if item["group"] == "normal") >= 5
    assert any(item["expect_outcome"] == "hold" for item in fixtures)


def test_every_fixture():
    for item in load_fixtures():
        wallet = wallet_signals(
            item["amount"],
            item["recipient"],
            item["method"],
            set(item["known_recipients"]),
            item["history_amounts"],
        )
        merged = {**wallet, **item["signals"]}
        result = score_signals(merged, "en")
        assert result.outcome == item["expect_outcome"], item["name"]
        if "expect_stage" in item:
            assert result.stage == item["expect_stage"], item["name"]
        if "expect_stage_min" in item:
            assert result.stage >= item["expect_stage_min"], item["name"]
        fired = [key for key in POINTS if merged.get(key)]
        assert len(result.reasons) == len(fired)
        assert all(result.reasons)


def test_no_single_signal_can_hold():
    for key in POINTS:
        result = score_signals({key: True}, "en")
        assert result.outcome == "allow"
        assert result.score == POINTS[key]
        assert result.score < 40


def test_score_caps_at_100():
    result = score_signals({key: True for key in POINTS}, "en")
    assert result.score == 100
    assert result.outcome == "hold"


def test_user_cannot_release_a_hold():
    assert user_may_continue("hold") is False
    assert user_may_continue("verify") is True
    assert user_may_continue("allow") is False
    assert contact_may_release("hold", "approved") is True
    assert contact_may_release("hold", "denied") is False
    assert contact_may_release("hold", None) is False


def test_irs_text_holds_without_gemini():
    text = load_sample("en")
    labels = label_heuristic(text, "en")
    wallet = wallet_signals(2000, "IRS Collections", "instant", {"cps energy"}, [140, 900])
    result = score_signals({**wallet, **labels.signals}, "en", labels.reasons)
    assert result.outcome == "hold"
    assert result.stage >= 3
    assert len(result.reasons) >= 3


def test_spanish_irs_text_holds_without_gemini():
    text = load_sample("es")
    labels = label_heuristic(text, "es")
    wallet = wallet_signals(2000, "IRS Collections", "instant", {"cps energy"}, [140, 900])
    result = score_signals({**wallet, **labels.signals}, "es", labels.reasons)
    assert result.outcome == "hold"
    assert result.stage >= 3


def test_normal_bill_text_does_not_hold():
    labels = label_heuristic("Monthly electric bill. No rush.", "en")
    wallet = wallet_signals(140, "CPS Energy", "ach", {"cps energy"}, [900, 140])
    result = score_signals({**wallet, **labels.signals}, "en")
    assert result.outcome == "allow"
    assert result.score < 40


def test_redact_hides_codes_and_keeps_amounts():
    cleaned = redact("Pay $2,000 today. Your verification code is 482913.")
    assert "482913" not in cleaned
    assert "2,000" in cleaned
    assert "[redacted]" in cleaned


def test_pressure_needs_a_baseline_before_a_spike_counts():
    start = datetime(2026, 10, 3, tzinfo=timezone.utc)
    flat = [(start + timedelta(seconds=index), 70, 14) for index in range(4)]
    ready, elevated = pressure_status(flat)
    assert ready is False
    assert elevated is False
    calm = [(start + timedelta(seconds=index * 5), 70, 14) for index in range(4)]
    calm.append((start + timedelta(seconds=20), 72, 14))
    ready, elevated = pressure_status(calm)
    assert ready is True
    assert elevated is False
    spiked = calm[:-1] + [(start + timedelta(seconds=20), 110, 14)]
    ready, elevated = pressure_status(spiked)
    assert ready is True
    assert elevated is True
