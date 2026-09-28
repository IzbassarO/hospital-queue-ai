"""Transparency-ledger endpoints and decision receipts over HTTP (docs/api.md §6, docs/transparency-ledger.md).

Every test that writes runs under `ledger_isolation` (conftest.py): its decisions and publications, and the ledger
entries they append, are rolled back, so the database the suite runs against keeps verifying.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx
import pytest

from conftest import API, auth

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ledger_verify  # noqa: E402

pytestmark = pytest.mark.anyio

ENDPOINTS = [
    "/transparency/head",
    "/transparency/entries",
    "/transparency/entries/1",
    "/transparency/lookup?subject=ledger:aqyl-kezek",
    "/transparency/verify",
    "/transparency/export",
]


@pytest.fixture
async def viewer(api_keys) -> httpx.AsyncClient:
    from conftest import _http_client

    async with _http_client(auth(api_keys["viewer"])) as http:
        yield http


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_every_endpoint_needs_a_key_and_a_viewer_is_enough(anon_client, viewer, path):
    assert (await anon_client.get(f"{API}{path}")).status_code == 401
    assert (await viewer.get(f"{API}{path}")).status_code == 200


async def test_head_names_the_protocol_and_the_genesis(viewer):
    head = (await viewer.get(f"{API}/transparency/head")).json()
    assert head["protocol"] == "aqyl-kezek-transparency-ledger" and head["protocol_version"] == 1
    assert head["canonicalization"] == "hqai-canonical-json-v1"
    assert head["genesis_hash"] == ledger_verify.entry_hash({**ledger_verify.GENESIS})
    assert head["seq"] == head["chain_length"] >= 1
    first = (await viewer.get(f"{API}/transparency/entries/1")).json()
    assert first["event_type"] == "ledger.genesis" and first["entry_hash"] == head["genesis_hash"]


async def test_entries_are_paged_in_seq_order_with_bounded_pages(viewer):
    newest = (await viewer.get(f"{API}/transparency/entries", params={"limit": 5})).json()
    oldest = (await viewer.get(f"{API}/transparency/entries", params={"limit": 5, "order": "asc"})).json()
    assert oldest["items"][0]["seq"] == 1
    assert [e["seq"] for e in newest["items"]] == sorted((e["seq"] for e in newest["items"]), reverse=True)
    assert newest["total"] == oldest["total"] >= 1
    assert (await viewer.get(f"{API}/transparency/entries", params={"limit": 501})).status_code == 422
    assert (await viewer.get(f"{API}/transparency/entries", params={"order": "random"})).status_code == 422
    assert (await viewer.get(f"{API}/transparency/entries/999999999")).status_code == 404
    assert (await viewer.get(f"{API}/transparency/entries/0")).status_code == 422


async def test_lookup_by_hash_prefix_or_subject(viewer):
    genesis = (await viewer.get(f"{API}/transparency/entries/1")).json()
    by_prefix = await viewer.get(f"{API}/transparency/lookup", params={"entry_hash": genesis["entry_hash"][:8]})
    assert [e["seq"] for e in by_prefix.json()] == [1]
    by_subject = await viewer.get(f"{API}/transparency/lookup", params={"subject": "ledger:aqyl-kezek"})
    assert by_subject.json()[0]["entry_hash"] == genesis["entry_hash"]
    for params in ({}, {"entry_hash": "abc"}, {"entry_hash": "zzzzzzzz"}, {"entry_hash": "a" * 8, "subject": "x"}):
        assert (await viewer.get(f"{API}/transparency/lookup", params=params)).status_code == 422, params


async def _decision(client, **extra) -> httpx.Response:
    payload = {
        "origin": "2025-03-17",
        "run_id": f"run-pytest-{uuid.uuid4().hex[:6]}",
        "sim_day": 3,
        "subject_kind": "alert",
        "subject_id": f"signal-{uuid.uuid4().hex[:6]}",
        "region_code": None,
        "org_code": None,
        "profile_code": None,
        "action": "clarify",
        "comment": "Уточнить у приёмного отделения — Қабылдау бөлімі",
        "actor": "pytest",
        "idempotency_key": f"pytest-{uuid.uuid4()}",
        **extra,
    }
    return await client.post(f"{API}/specialist-decisions", json=payload), payload


async def test_decision_receipt_replay_listing_and_verification(client, viewer, ledger_isolation):
    head_before = (await viewer.get(f"{API}/transparency/head")).json()
    created, payload = await _decision(client)
    assert created.status_code == 201, created.text
    receipt = created.json()["receipt"]
    assert receipt["ledger_seq"] == head_before["seq"] + 1
    assert receipt["event_type"] == "decision.recorded"
    assert receipt["subject"] == f"specialist_decision:{created.json()['id']}"
    assert receipt["verify_path"] == f"/verify?seq={receipt['ledger_seq']}"

    replay = await client.post(f"{API}/specialist-decisions", json=payload)
    assert replay.status_code == 200 and replay.json()["receipt"] == receipt
    assert (await viewer.get(f"{API}/transparency/head")).json()["seq"] == receipt["ledger_seq"]

    listed = await viewer.get(f"{API}/specialist-decisions", params={"run_id": payload["run_id"]})
    assert listed.json()["items"][0]["receipt"] == receipt

    entry = (await viewer.get(f"{API}/transparency/entries/{receipt['ledger_seq']}")).json()
    assert entry["entry_hash"] == receipt["entry_hash"] and entry["prev_hash"] == head_before["entry_hash"]
    assert payload["comment"] not in str(entry) and "pytest" not in str(entry["payload"]["commitments"])
    assert (
        entry["payload"]["evidence"]["operational_publication_identity_sha256"]
        == created.json()["publication_identity_sha256"]
    )

    report = (await viewer.get(f"{API}/transparency/verify")).json()
    assert report["status"] == "OK", report
    assert report["verified_through_seq"] == report["head_seq"] == receipt["ledger_seq"]
    assert report["reason_code"] is None and report["issues"] == []


async def test_hospital_decision_carries_a_receipt(client, high_load, ledger_isolation):
    payload = {
        "region_code": high_load["region_code"],
        "org_code": high_load["org_code"],
        "profile_code": high_load["profile_code"],
        "action": "defer",
        "comment": "Ждём подтверждения",
        "actor": f"pytest-{uuid.uuid4().hex[:6]}",
        "idempotency_key": f"pytest-{uuid.uuid4()}",
    }
    created = await client.post(f"{API}/decisions", json=payload)
    assert created.status_code == 201, created.text
    receipt = created.json()["receipt"]
    assert receipt["subject"] == f"hospital_decision:{created.json()['id']}"
    replay = await client.post(f"{API}/decisions", json=payload)
    assert replay.status_code == 200 and replay.json()["receipt"] == receipt


async def test_export_is_public_canonical_and_verifies_offline(client, viewer, ledger_isolation):
    created, payload = await _decision(client, comment="Совершенно частный комментарий 7f3a")
    export = await viewer.get(f"{API}/transparency/export")
    assert export.headers["content-type"].startswith("application/x-ndjson")
    assert "attachment" in export.headers["content-disposition"]
    text = export.text
    assert payload["comment"] not in text and payload["idempotency_key"] not in text and '"salt"' not in text
    summary = ledger_verify.verify_lines(text.splitlines(keepends=True))
    assert summary["head_seq"] == created.json()["receipt"]["ledger_seq"]
    assert summary["head_hash"] == created.json()["receipt"]["entry_hash"]


async def test_viewer_cannot_write_but_can_verify(viewer):
    created = await viewer.post(f"{API}/specialist-decisions", json={})
    assert created.status_code == 403
    assert (await viewer.get(f"{API}/transparency/verify")).json()["mode"] == "server"
