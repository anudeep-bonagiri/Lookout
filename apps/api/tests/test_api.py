from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

from app.config import get_settings
from app.db import ApprovalRequest, init_db, session_factory, utcnow
from app.main import create_app
from app.service import ROSA_ID, seed

IRS = (
    "This is the IRS. A warrant has been issued for your arrest. "
    "You must pay $2,000 by instant transfer. Stay on the line. "
    "Do not tell anyone. Your verification code is 482913."
)


@pytest.fixture
async def client(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 't.db'}"
    get_settings.cache_clear()
    app = create_app(url)
    await init_db()
    factory = session_factory()
    async with factory() as session:
        await seed(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.mark.asyncio
async def test_irs_payment_is_held_and_code_is_not_shared(client: AsyncClient):
    response = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 2000,
            "recipient": "IRS Collections",
            "method": "instant",
            "prompt_text": IRS,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "hold"
    assert body["stage"] >= 3
    assert body["approval_id"]
    assert len(body["reasons"]) >= 3
    assert "482913" not in response.text

    crew = await client.get("/crew/maya-demo")
    assert crew.status_code == 200
    pending = crew.json()["pending"]
    assert pending["approval_id"] == body["approval_id"]
    assert "482913" not in pending["user_report"]
    assert "Fact" not in pending
    assert pending["fact"]
    assert pending["unknown"]
    assert pending["action"]

    blocked = await client.post(f"/attempts/{body['attempt_id']}/continue", json={"user_id": ROSA_ID})
    assert blocked.status_code == 400

    denied = await client.post(
        f"/approvals/{body['approval_id']}/decide",
        json={"token": "maya-demo", "decision": "denied"},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "denied"


@pytest.mark.asyncio
async def test_normal_bill_is_allowed(client: AsyncClient):
    response = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 140,
            "recipient": "CPS Energy",
            "method": "ach",
            "prompt_text": "Monthly electric bill. No rush.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "allow"
    assert body["score"] < 40
    assert body["approval_id"] is None


@pytest.mark.asyncio
async def test_message_check_does_not_open_a_payment(client: AsyncClient):
    before = await client.get("/history", params={"token": "maya-demo"})
    count = len(before.json()["items"])
    response = await client.post(
        "/message-check",
        json={"user_id": ROSA_ID, "prompt_text": IRS},
    )
    assert response.status_code == 200
    assert response.json()["stage"] >= 3
    assert response.json()["saved_payment"] is False
    after = await client.get("/history", params={"token": "maya-demo"})
    assert len(after.json()["items"]) == count


@pytest.mark.asyncio
async def test_verify_can_continue_until_the_contact_is_asked(client: AsyncClient):
    response = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 50,
            "recipient": "Cousin Luis",
            "method": "ach",
            "prompt_text": "This is the IRS. A warrant has been issued for your arrest.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "verify"
    continued = await client.post(f"/attempts/{body['attempt_id']}/continue", json={"user_id": ROSA_ID})
    assert continued.status_code == 200
    assert continued.json()["status"] == "allowed"


@pytest.mark.asyncio
async def test_wrong_person_cannot_approve(client: AsyncClient):
    response = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 2000,
            "recipient": "IRS Collections",
            "method": "instant",
            "prompt_text": IRS,
        },
    )
    approval_id = response.json()["approval_id"]
    rejected = await client.post(
        f"/approvals/{approval_id}/decide",
        json={"token": "someone-else", "decision": "approved"},
    )
    assert rejected.status_code == 404


@pytest.mark.asyncio
async def test_unanswered_hold_expires(client: AsyncClient):
    response = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 2000,
            "recipient": "IRS Collections",
            "method": "instant",
            "prompt_text": IRS,
        },
    )
    body = response.json()
    factory = session_factory()
    async with factory() as session:
        await session.execute(
            update(ApprovalRequest)
            .where(ApprovalRequest.id == body["approval_id"])
            .values(created_at=utcnow() - timedelta(minutes=11))
        )
        await session.commit()
    viewed = await client.get("/attempts/" + body["attempt_id"], params={"user_id": ROSA_ID})
    assert viewed.status_code == 200
    assert viewed.json()["status"] == "expired"
    assert viewed.json()["approval_status"] == "expired"


@pytest.mark.asyncio
async def test_chart_and_alarm(client: AsyncClient):
    chart = await client.get("/history/chart", params={"token": "maya-demo"})
    assert chart.status_code == 200
    payload = chart.json()
    assert payload["tiger"] is False
    assert payload["buckets"]
    alarm = await client.get("/alarms/active", params={"home_id": "rosa"})
    assert alarm.json()["active"] is False
    held = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 2000,
            "recipient": "IRS Collections",
            "method": "instant",
            "prompt_text": IRS,
        },
    )
    assert held.json()["outcome"] == "hold"
    alarm = await client.get("/alarms/active", params={"home_id": "rosa"})
    assert alarm.json()["active"] is True


@pytest.mark.asyncio
async def test_stated_reason_learns_from_success_and_denial(client: AsyncClient):
    ranked = await client.get("/reasons", params={"language": "en"})
    assert ranked.status_code == 200
    before = {item["id"]: item for item in ranked.json()["reasons"]}
    assert before["threat"]["rank"] < before["bill"]["rank"]
    assert before["bill"]["points"] == 0
    assert before["threat"]["points"] < 40

    held = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 2000,
            "recipient": "IRS Collections",
            "method": "instant",
            "prompt_text": IRS,
            "why": "threat",
        },
    )
    assert held.status_code == 200, held.text
    assert held.json()["outcome"] == "hold"
    denied = await client.post(
        f"/approvals/{held.json()['approval_id']}/decide",
        json={"token": "maya-demo", "decision": "denied"},
    )
    assert denied.status_code == 200

    after = await client.get("/reasons", params={"language": "en"})
    learned = {item["id"]: item for item in after.json()["reasons"]}
    assert learned["threat"]["disputes"] == 1
    assert learned["threat"]["q"] > before["threat"]["q"]

    threat = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 140,
            "recipient": "CPS Energy",
            "method": "ach",
            "prompt_text": "",
            "why": "threat",
        },
    )
    assert threat.status_code == 200, threat.text
    assert threat.json()["outcome"] == "allow"
    assert threat.json()["score"] < 40
    assert threat.json()["stage"] == 2

    bill = await client.post(
        "/check",
        json={
            "user_id": ROSA_ID,
            "amount": 140,
            "recipient": "CPS Energy",
            "method": "ach",
            "prompt_text": "Monthly electric bill.",
            "why": "bill",
        },
    )
    assert bill.status_code == 200, bill.text
    assert bill.json()["outcome"] == "allow"
    assert bill.json()["score"] < 40
    assert bill.json()["why"]["successes"] == 1


@pytest.mark.asyncio
async def test_doctor_call_is_reviewed_without_joining_the_line(client: AsyncClient):
    response = await client.post(
        "/message-check",
        json={
            "user_id": ROSA_ID,
            "prompt_text": "I'm at the doctor. Send the money now. Don't tell Mom.",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved_payment"] is False
    assert body["outcome"] != "hold"
    assert body["score"] < 70
    assert body["suggested_why"]["id"] == "emergency"
    assert body["suggested_why"]["points"] < 40
    assert "did not join the call" in body["review_note"]
    assert any(item["id"] == "emergency-desk" for item in body["looked"])

    added = await client.post(
        "/watchers",
        json={
            "name": "Booth desk",
            "phrases": ["purple ostrich"],
            "signal": "secrecy",
            "sentence": "Those words were added at the table.",
        },
    )
    assert added.status_code == 200, added.text
    custom = await client.post(
        "/message-check",
        json={"user_id": ROSA_ID, "prompt_text": "Please pay the purple ostrich today."},
    )
    assert custom.status_code == 200, custom.text
    custom_body = custom.json()
    assert custom_body["outcome"] == "allow"
    assert custom_body["score"] < 40
    assert custom_body["signals"]["secrecy"] is True
    assert any(item["name"] == "Booth desk" for item in custom_body["looked"])
    history = await client.get("/history", params={"token": "maya-demo"})
    assert all(item["recipient"] != "doctor" for item in history.json()["items"])
