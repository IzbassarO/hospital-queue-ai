"""API tests against the running Postgres (marts must be built: `make marts`).

By default the app runs in-process (httpx + ASGI transport), so the tests exercise the current code.
Set HQAI_API_BASE_URL (e.g. http://localhost:8000) to run the same tests against a running server,
such as the docker `backend` service.

The suite creates one API key per role (labels `pytest-<run>-<role>`) directly in the database and at the end
removes those keys, the access-log rows made with them and the decisions it created. Requests the tests send
without a key (401 checks) stay in access_log: anonymous rows cannot be told apart from anyone else's.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from sqlalchemy import delete

from app.core.security import API_KEY_HEADER, ROLES
from app.db.models import AccessLog, ApiKey, DecisionLog
from app.db.session import SessionLocal
from app.services import admin

API = "/api/v1"
TEST_ACTOR_PREFIX = "pytest-"
RUN_ID = uuid.uuid4().hex[:8]
KEY_LABEL_PREFIX = f"pytest-{RUN_ID}-"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def api_keys() -> Iterator[dict[str, str]]:
    """{role: key} for viewer, specialist and admin; also any extra keys whose label starts with the run prefix
    are cleaned up (tests that create or revoke keys use that prefix)."""
    with SessionLocal() as session:
        keys = {role: admin.create_key(session, role, f"{KEY_LABEL_PREFIX}{role}").key for role in ROLES}
    yield keys
    with SessionLocal() as session:
        session.execute(delete(AccessLog).where(AccessLog.key_label.startswith(KEY_LABEL_PREFIX)))
        session.execute(delete(ApiKey).where(ApiKey.label.startswith(KEY_LABEL_PREFIX)))
        session.commit()


def auth(key: str) -> dict[str, str]:
    return {API_KEY_HEADER: key}


def _http_client(headers: dict[str, str] | None = None) -> httpx.AsyncClient:
    base_url = os.environ.get("HQAI_API_BASE_URL")
    if base_url:
        return httpx.AsyncClient(base_url=base_url, timeout=30, headers=headers)
    from app.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30, headers=headers
    )


@pytest.fixture(scope="session")
async def anon_client() -> AsyncIterator[httpx.AsyncClient]:
    """Client without an API key."""
    async with _http_client() as http:
        health = await http.get(f"{API}/health")
        if health.status_code != 200 or health.json().get("marts_as_of_date") is None:
            pytest.exit(
                f"API not ready ({health.status_code}: {health.text}) — run `make up && make marts`", returncode=2
            )
        yield http


@pytest.fixture(scope="session")
async def client(anon_client: httpx.AsyncClient, api_keys: dict[str, str]) -> AsyncIterator[httpx.AsyncClient]:
    """Client authenticated as a specialist (reads everything and may record decisions)."""
    async with _http_client(auth(api_keys["specialist"])) as http:
        yield http


@pytest.fixture(scope="session")
def created_decision_ids() -> Iterator[list[int]]:
    """Decisions created by tests; deleted at the end so the human-in-the-loop log stays clean."""
    ids: list[int] = []
    yield ids
    with SessionLocal() as session:
        session.execute(
            delete(DecisionLog).where(DecisionLog.id.in_(ids) | DecisionLog.actor.startswith(TEST_ACTOR_PREFIX))
        )
        session.commit()


@pytest.fixture(scope="session")
async def high_load(client: httpx.AsyncClient) -> dict:
    """The hospital × profile with the highest load_index nationally (first alert)."""
    response = await client.get(f"{API}/alerts", params={"limit": 1})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items, "no alerts: marts look empty"
    return items[0]
