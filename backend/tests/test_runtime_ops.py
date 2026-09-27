"""Runtime hardening: connection pool and statement timeout, one session per request, the request id that ties a
log line to an `access_log` row, what the audit row may and may not contain, the database role split, and the two
proxy limits that protect the API (docs/security.md §2)."""

import inspect
import json
import logging
import os
import re
import uuid

import anyio
import pytest
from sqlalchemy import event, select, text

from app.core.access_log import client_ip_for, trusted_networks, writer
from app.core.config import REPO_ROOT, Settings, get_settings
from app.core.logging import JsonFormatter, RequestIdFilter, request_id_for, request_id_var
from app.db.models import AccessLog
from app.db.session import ApiSessionLocal, SessionLocal, api_engine
from app.services import assistant
from conftest import API, auth

pytestmark = pytest.mark.anyio

IN_PROCESS_ONLY = pytest.mark.skipif(
    bool(os.environ.get("HQAI_API_BASE_URL")), reason="inspects the engine and middleware of this process"
)
DOCKER_BRIDGE_PEER = "172.18.0.5"


# ------------------------------------------------------------------------------------- client address (C13)
def test_forwarded_for_is_believed_only_behind_a_trusted_proxy():
    networks = trusted_networks(get_settings().trusted_proxy_cidrs)
    assert client_ip_for(DOCKER_BRIDGE_PEER, "203.0.113.7, 172.18.0.5", networks) == "203.0.113.7"
    assert client_ip_for(DOCKER_BRIDGE_PEER, None, networks) == DOCKER_BRIDGE_PEER
    # a caller reaching the API directly can claim anything: the address it connected from is what is recorded
    assert client_ip_for("198.51.100.4", "203.0.113.7", networks) == "198.51.100.4"
    assert client_ip_for(None, "203.0.113.7", networks) is None


def test_unparsable_trusted_network_is_ignored():
    networks = trusted_networks(["172.16.0.0/12", "not-a-network"])
    assert len(networks) == 1
    assert client_ip_for(DOCKER_BRIDGE_PEER, "203.0.113.7", networks) == "203.0.113.7"


# ------------------------------------------------------------------------------------- request id and logs (C28)
def test_request_id_is_taken_from_the_caller_only_when_it_is_well_formed():
    supplied = {"headers": [(b"x-request-id", b"trace-42_ok")]}
    assert request_id_for(supplied) == "trace-42_ok"
    forged = {"headers": [(b"x-request-id", b"drop table; \n")]}
    assert request_id_for(forged) != "drop table; \n"
    assert len(request_id_for({"headers": []})) == 32


def test_log_lines_are_json_and_carry_the_current_request_id():
    record = logging.LogRecord("hqai.test", logging.WARNING, __file__, 1, "signal %s", ("HIGH",), None)
    token = request_id_var.set("trace-42")
    try:
        assert RequestIdFilter().filter(record)
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["level"] == "WARNING"
    assert line["logger"] == "hqai.test"
    assert line["message"] == "signal HIGH"
    assert line["request_id"] == "trace-42"
    assert line["ts"].endswith("Z")


async def test_response_echoes_the_callers_request_id(anon_client):
    supplied = f"pytest-{uuid.uuid4().hex}"
    response = await anon_client.get(f"{API}/health", headers={"X-Request-ID": supplied})
    assert response.status_code == 200
    assert response.headers["x-request-id"] == supplied
    generated = await anon_client.get(f"{API}/health")
    assert generated.headers["x-request-id"] not in ("", supplied)


# ------------------------------------------------------------------------------------- what the audit row holds (C13)
async def test_audit_row_keeps_the_query_string_and_the_request_id(anon_client, api_keys):
    marker = uuid.uuid4().hex
    supplied = f"pytest-{marker}"
    response = await anon_client.get(
        f"{API}/alerts",
        params={"limit": 1, "probe": marker},
        headers={**auth(api_keys["viewer"]), "X-Request-ID": supplied},
    )
    assert response.status_code == 200
    row = await _wait_for_row(marker)
    assert row is not None, "the request was not recorded"
    assert row.query is not None and f"probe={marker}" in row.query
    assert row.request_id == supplied
    assert row.status == 200 and row.role == "viewer"


async def test_cors_preflight_is_not_recorded(anon_client):
    marker = uuid.uuid4().hex
    preflight = await anon_client.options(
        f"{API}/alerts",
        params={"probe": marker},
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )
    assert preflight.status_code == 200, preflight.text
    await anyio.sleep(0.6)
    assert await _wait_for_row(marker, attempts=1) is None, "preflights carry no identity and are not logged"


async def _wait_for_row(marker: str, attempts: int = 12) -> AccessLog | None:
    """The writer commits in batches, so a row appears shortly after the response (app/core/access_log.py)."""
    for attempt in range(attempts):
        with SessionLocal() as session:
            row = session.scalar(select(AccessLog).where(AccessLog.query.contains(marker)))
        if row is not None or attempt == attempts - 1:
            return row
        await anyio.sleep(0.25)
    return None


# ------------------------------------------------------------------------------------- pool and timeout (C29)
@IN_PROCESS_ONLY
def test_request_sessions_are_pooled_and_time_bounded():
    settings = get_settings()
    assert api_engine.pool.size() == settings.db_pool_size
    with ApiSessionLocal() as session:
        assert session.scalar(text("show statement_timeout")) != "0"
    with SessionLocal() as session:
        # the seed loader and the publish commands run here: a COPY or a bundle publish outlives any request limit
        assert session.scalar(text("show statement_timeout")) == "0"


@IN_PROCESS_ONLY
async def test_a_request_opens_one_database_session(client):
    await writer.drain()
    await anyio.sleep(0.4)
    checkouts = 0

    def count(*_args):
        nonlocal checkouts
        checkouts += 1

    event.listen(api_engine, "checkout", count)
    try:
        for _ in range(10):
            assert (await client.get(f"{API}/overview")).status_code == 200
    finally:
        event.remove(api_engine, "checkout", count)
    # 10 request sessions; the batched access-log writer may add one or two commits of its own inside the window
    assert 10 <= checkouts <= 13, f"{checkouts} sessions for 10 requests (2 per request before the batching writer)"


# ------------------------------------------------------------------------------------- database role split (C25)
def test_the_api_falls_back_to_the_owner_role_when_no_application_role_is_configured():
    demo = Settings(app_db_user="", app_db_password="")
    assert demo.api_database_url == demo.database_url
    configured = Settings(app_db_user="hqai_app", app_db_password="secret")
    assert "hqai_app:secret@" in configured.api_database_url
    assert configured.database_url == demo.database_url, "migrations and pipelines keep the owner role"


def test_the_database_needs_no_extension():
    init_sql = (REPO_ROOT / "db" / "init.sql").read_text(encoding="utf-8")
    assert "CREATE EXTENSION" not in init_sql, "a DBA-managed PostgreSQL provides no contrib packages"
    assert "NOSUPERUSER" in init_sql


# ------------------------------------------------------------------------------------- proxy limits (C22)
def test_the_proxy_limits_api_and_assistant_rates():
    """The /api guard is a flood guard, not a quota: it has to clear the control centre's own opening burst.

    One first paint asks for the signal pages plus a hospital card per attention row (up to 120), all in flight
    together, so a burst below that shows the specialist 429s instead of a map. The assistant is the opposite
    case: one upstream call can occupy a worker for tens of seconds, so it stays deliberately tight.
    """
    template = (REPO_ROOT / "frontend" / "nginx.conf.template").read_text(encoding="utf-8")
    zones = dict(re.findall(r"limit_req_zone \$binary_remote_addr zone=(\w+):\d+m rate=(\d+)r/s", template))
    bursts = dict(re.findall(r"limit_req zone=(\w+) burst=(\d+)", template))
    assert int(bursts["hqai_api"]) >= 200, "below the UI's own opening burst of signal pages plus ~120 cards"
    assert int(zones["hqai_api"]) >= 50
    assert "limit_req zone=hqai_api burst=" in template and "nodelay;" in template
    assert int(zones["hqai_assistant"]) <= 2 and int(bursts["hqai_assistant"]) <= 5


def test_the_proxy_waits_longer_for_the_assistant_than_the_backend_does():
    template = (REPO_ROOT / "frontend" / "nginx.conf.template").read_text(encoding="utf-8")
    block = template.split("location = /api/v1/assistant")[1].split("}")[0]
    proxy_read_timeout = int(re.search(r"proxy_read_timeout (\d+)s", block).group(1))
    backend_timeout = inspect.signature(assistant.ask).parameters["timeout"].default
    assert proxy_read_timeout > backend_timeout, "nginx must not 504 while the backend is still waiting"
