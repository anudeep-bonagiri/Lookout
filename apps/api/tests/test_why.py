from app.labels import label_heuristic
from app.why import FLOOR, apply, contribution, posterior, rank, suggest


def test_priors_rank_a_threat_above_a_bill():
    rows = rank({})
    order = [item["id"] for item in rows]
    assert order[0] == "threat"
    assert order[-1] == "bill"
    assert rows[0]["level"] == "high"
    assert rows[-1]["level"] == "low"
    assert rows[-1]["points"] == 0


def test_one_reason_cannot_hold():
    for item in rank({}):
        assert contribution(item["id"], item["q"]) < 40
        signals, weight = apply({}, item["id"], item["q"])
        assert weight <= 15
        if item["q"] < FLOOR:
            assert signals == {}
            assert weight == 0


def test_dispute_raises_q_and_success_lowers_it():
    prior = 0.70
    start = posterior(prior, 0, 0)
    denied = posterior(prior, 0, 1)
    finished = posterior(prior, 1, 0)
    step = 1 / 5
    assert denied == start + step * (1 - start)
    assert finished == start + step * (0 - start)
    assert denied > start > finished


def test_doctor_call_is_an_emergency_and_cannot_hold_alone():
    text = "I'm at the doctor. Send the money now. Don't tell Mom."
    labels = label_heuristic(text, "en")
    assert labels.signals["urgency"] is True
    assert labels.signals["secrecy"] is True
    assert suggest(text) == "emergency"
    assert suggest("I'm at the doctor, give me the money.") == "emergency"
    item = next(row for row in rank({}) if row["id"] == "emergency")
    assert item["points"] < 40
    assert item["rank"] < next(row["rank"] for row in rank({}) if row["id"] == "bill")


def test_a_bill_stays_low_until_disputes_pile_up():
    quiet = posterior(0.08, 0, 1)
    assert quiet < FLOOR
    learned = posterior(0.08, 0, 6)
    assert learned > FLOOR
    assert contribution("bill", learned) <= 15
