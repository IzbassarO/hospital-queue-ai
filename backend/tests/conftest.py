"""API tests against the running Postgres (marts must be built: `make marts`).

By default the app runs in-process (httpx + ASGI transport), so the tests exercise the current code.
Set HQAI_API_BASE_URL (e.g. http://localhost:8000) to run the same tests against a running server,
such as the docker `backend` service.
"""
import os
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from sqlalchemy import delete

from app.db.models import DecisionLog
from app.db.session import SessionLocal

API = "/api/v1"
TEST_ACTOR_PREFIX = "pytest-"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
async def client() -> AsyncIterator[httpx.AsyncClient]:
    base_url = os.environ.get("HQAI_API_BASE_URL")
    if base_url:
        http = httpx.AsyncClient(base_url=base_url, timeout=30)
    else:
        from app.main import app

        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=30)
    async with http:
        health = await http.get(f"{API}/health")
        if health.status_code != 200 or health.json().get("marts_as_of_date") is None:
            pytest.exit(f"API not ready ({health.status_code}: {health.text}) — run `make up && make marts`",
                        returncode=2)
        yield http


@pytest.fixture(scope="session")
def created_decision_ids() -> Iterator[list[int]]:
    """Decisions created by tests; deleted at the end so the human-in-the-loop log stays clean."""
    ids: list[int] = []
    yield ids
    if ids:
        with SessionLocal() as session:
            session.execute(delete(DecisionLog).where(DecisionLog.id.in_(ids)))
            session.commit()


@pytest.fixture(scope="session")
async def high_load(client: httpx.AsyncClient) -> dict:
    """The hospital × profile with the highest load_index nationally (first alert)."""
    response = await client.get(f"{API}/alerts", params={"limit": 1})
    assert response.status_code == 200
    items = response.json()["items"]
    assert items, "no alerts: marts look empty"
    return items[0]
