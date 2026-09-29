"""API tests against the running Postgres (marts must be built: `make marts`).

By default the app runs in-process (httpx + ASGI transport), so the tests exercise the current code.
Set HQAI_API_BASE_URL (e.g. http://localhost:8000) to run the same tests against a running server,
such as the docker `backend` service.

The suite creates one API key per role (labels `pytest-<run>-<role>`) directly in the database and at the end
removes those keys, the access-log rows made with them and the decisions it created. Requests the tests send
without a key (401 checks) stay in access_log: anonymous rows cannot be told apart from anyone else's.

Tests that publish bundles or record decisions request `ledger_isolation`: those writes append to the append-only
transparency ledger, which no cleanup can undo, so the whole test — its own sessions and the in-process API's —
runs in one transaction that is rolled back at the end. Nothing it wrote, ledger entries included, reaches the
database, and the ledger of the database the suite runs against keeps verifying (docs/transparency-ledger.md).
"""

import os
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.core.security import API_KEY_HEADER, ROLES
from app.db import session as db_session
from app.db.models import AccessLog, ApiKey, DecisionLog
from app.db.session import SessionLocal, engine
from app.services import admin

TESTS_DIR = Path(__file__).resolve().parent

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


@pytest.fixture
def ledger_isolation(monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker]:
    """One outer transaction for the whole test, rolled back at the end.

    Every `SessionLocal` the test modules imported and the in-process API's request session are bound to one
    connection whose transaction is never committed: their own commits and `session.begin()` blocks become
    savepoints. Against an external server (HQAI_API_BASE_URL) the API cannot join the transaction, so the fixture
    yields the ordinary factory and the test's writes are real.
    """
    original = db_session.SessionLocal
    if os.environ.get("HQAI_API_BASE_URL"):
        yield original
        return
    from app.main import app

    connection = engine.connect()
    outer = connection.begin()
    factory = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", autoflush=False, expire_on_commit=False
    )
    for module in list(sys.modules.values()):
        module_file = getattr(module, "__file__", None) or ""
        if Path(module_file).parent == TESTS_DIR and getattr(module, "SessionLocal", None) is original:
            monkeypatch.setattr(module, "SessionLocal", factory)

    def request_session() -> Iterator:
        with factory() as session:
            yield session

    app.dependency_overrides[db_session.get_session] = request_session
    try:
        yield factory
    finally:
        app.dependency_overrides.pop(db_session.get_session, None)
        outer.rollback()
        connection.close()


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
