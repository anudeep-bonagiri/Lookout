from app.watchers import apply_watchers, load_desks


def test_a_new_desk_adds_one_capped_signal():
    load_desks()
    from app.watchers import DESKS

    invoice = next(item for item in DESKS if item["id"] == "invoice-desk")
    signals, hits = apply_watchers("Please use the new account number.", {}, [invoice], "en")
    assert signals["sensitive_request"] is True
    assert hits[0]["heat"] == 15
    again, second = apply_watchers("Please use the new account number.", signals, [invoice], "en")
    assert second[0]["heat"] == 0
    assert again["sensitive_request"] is True


def test_stranded_and_emergency_are_desks():
    load_desks()
    from app.watchers import DESKS

    ids = {item["id"] for item in DESKS}
    assert {"emergency-desk", "invoice-desk", "stranded-desk"} <= ids
