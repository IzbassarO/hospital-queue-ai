"""Control-centre endpoints: specialist decisions persist and replay; the assistant proxy reports its state."""

import uuid

import pytest
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import SpecialistDecision
from app.db.session import SessionLocal
from conftest import API, _http_client, auth

pytestmark = pytest.mark.anyio


@pytest.fixture
async def viewer_client(api_keys):
    async with _http_client(auth(api_keys["viewer"])) as http:
        yield http


@pytest.fixture(scope="module")
def created_ids():
    ids: list[int] = []
    yield ids
    with SessionLocal() as session:
        session.execute(delete(SpecialistDecision).where(SpecialistDecision.id.in_(ids)))
        session.commit()


async def test_specialist_decision_persists_and_replays(client, created_ids):
    key = f"pytest-{uuid.uuid4()}"
    run = f"run-pytest-{uuid.uuid4().hex[:6]}"
    payload = {
        "origin": "2025-03-17",
        "run_id": run,
        "sim_day": 1,
        "subject_kind": "patient",
        "subject_id": f"Н-{uuid.uuid4().hex[:4]}",
        "region_code": "39",
        "org_code": "000V",
        "profile_code": "391",
        "action": "confirm",
        "comment": "тест",
        "actor": "pytest",
        "idempotency_key": key,
    }
    created = await client.post(f"{API}/specialist-decisions", json=payload)
    assert created.status_code == 201, created.text
    body = created.json()
    created_ids.append(body["id"])
    assert {k: body[k] for k in payload} == payload and body["api_key_label"]

    replay = await client.post(f"{API}/specialist-decisions", json=payload)
    assert replay.status_code == 200 and replay.json()["id"] == body["id"]

    conflict = await client.post(f"{API}/specialist-decisions", json={**payload, "action": "postpone"})
    assert conflict.status_code == 409

    listed = await client.get(
        f"{API}/specialist-decisions", params={"origin": "2025-03-17", "subject_kind": "patient", "limit": 500}
    )
    assert listed.status_code == 200
    assert any(d["id"] == body["id"] for d in listed.json()["items"])

    by_run = await client.get(f"{API}/specialist-decisions", params={"run_id": run, "limit": 50})
    assert [d["id"] for d in by_run.json()["items"]] == [body["id"]]
    other_run = await client.get(f"{API}/specialist-decisions", params={"run_id": f"{run}-x", "limit": 50})
    assert other_run.json()["total"] == 0


async def test_specialist_decision_action_must_fit_subject(client):
    bad = {
        "origin": "2025-03-17",
        "sim_day": 0,
        "subject_kind": "alert",
        "subject_id": "abc",
        "action": "confirm",
    }
    response = await client.post(f"{API}/specialist-decisions", json=bad)
    assert response.status_code == 422


async def test_specialist_decisions_need_specialist_role(viewer_client):
    response = await viewer_client.post(
        f"{API}/specialist-decisions",
        json={"origin": "2025-03-17", "sim_day": 0, "subject_kind": "alert", "subject_id": "x", "action": "accept"},
    )
    assert response.status_code == 403


async def test_assistant_status_and_ask(client):
    status = await client.get(f"{API}/assistant/status")
    assert status.status_code == 200
    body = status.json()
    assert set(body) == {"configured", "provider", "model"}
    assert body["configured"] == bool(get_settings().assistant_api_key)
    if not body["configured"]:
        asked = await client.post(
            f"{API}/assistant",
            json={
                "lang": "ru",
                "question": "Стоит ли соглашаться?",
                "facts": ["Прогноз: 5,9 в день"],
                "explanation": ["тест"],
                "subject": {"kind": "alert", "id": "abc", "hospital": "Тест"},
            },
        )
        assert asked.status_code == 503
