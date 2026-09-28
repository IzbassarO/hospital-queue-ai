"""Replay safety of the transparency migrations (docs/transparency-ledger.md §9). No database needed.

Migration 0019 carries a frozen copy of protocol v1 (canonical JSON, genesis, commitments, payload builders, global
order) instead of importing app/, so a clean database migrated years from now gets exactly the bytes it gets today.
These tests hold the two copies together: the application's builders (live path, server verifier) must agree with
the frozen copy byte for byte, and the frozen copy itself must keep producing the pinned golden head.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
from pathlib import Path

from app.domain.transparency import chain, events
from app.domain.transparency.canonical import canonical_text

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "backend" / "alembic" / "versions"
VECTORS = json.loads((ROOT / "docs" / "transparency-ledger-vectors.json").read_text(encoding="utf-8"))
# The head of the frozen backfill of SOURCE below. Changing it means the historical migration changed: never do that
# to follow app code; a protocol change is a new migration and a new protocol version.
GOLDEN_BACKFILL_HEAD = "29bcd3c390707c9253e1591e5f4f60cc909a7551f77e0a38b3841960184c6df5"


def _load(name: str):
    path = next(VERSIONS.glob(f"{name}_*.py"))
    spec = importlib.util.spec_from_file_location(f"migration_{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


LEDGER, LEDGER_PATH = _load("0019")
T0 = dt.datetime(2025, 3, 17, 9, tzinfo=dt.UTC)


def _publication(i: int, kind: str) -> dict:
    return {
        "id": i,
        "publication_id": f"{kind}-{i}",
        "identity_sha256": f"{i:x}" * 64 if i < 16 else "f" * 64,
        "bundle_sha256": "b" * 64,
        "contract_version": "1.0.0",
        "schema_version": f"{kind}_v1",
        "source_code_commit": "1" * 40,
        "published_at": T0,
    }


PUBLICATIONS = {kind: [_publication(rank, kind)] for rank, kind in enumerate(events.PUBLICATION_KINDS, start=1)}
PUBLICATIONS["operational_intelligence"].append(
    {**_publication(9, "operational_intelligence"), "published_at": T0 - dt.timedelta(days=1)}
)
SPECIALIST = [
    {
        "id": 1, "created_at": T0, "origin": dt.date(2025, 3, 17), "run_id": "r1", "sim_day": 0,
        "subject_kind": "alert", "subject_id": "s-1", "region_code": "39", "org_code": "000V", "profile_code": "391",
        "action": "accept", "comment": "Согласовано\n\"да\"", "actor": "Иванова", "api_key_label": None,
        "idempotency_key": "pytest-key-1", "publication_identity_sha256": "2" * 64,
    },
    {
        "id": 2, "created_at": T0 - dt.timedelta(microseconds=1), "origin": dt.date(2025, 3, 17), "run_id": None,
        "sim_day": 3, "subject_kind": "patient", "subject_id": "Н-1", "region_code": None, "org_code": None,
        "profile_code": None, "action": "confirm", "comment": None, "actor": None, "api_key_label": "k",
        "idempotency_key": None, "publication_identity_sha256": None,
    },
]  # fmt: skip
HOSPITAL = [
    {
        "id": 1, "created_at": T0, "region_code": "39", "org_code": "000V", "profile_code": "391",
        "recommendation_id": "reco:000V:391:1", "action": "defer", "comment": "", "actor": "Дежурный врач",
        "alternative_org_code": "000W", "idempotency_key": None, "api_key_label": "pytest",
    },
]  # fmt: skip
SALTS = {"specialist_decision:1": "ab" * 32, "specialist_decision:2": "cd" * 32, "hospital_decision:1": "ef" * 32}


def _frozen() -> list[dict]:
    return LEDGER.backfill(PUBLICATIONS, HOSPITAL, SPECIALIST, SALTS)


def test_migrations_import_nothing_from_the_application() -> None:
    for name in ("0018", "0019"):
        _, path = _load(name)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                assert node.module and node.module.split(".")[0] != "app", f"{path.name} imports {node.module}"
            elif isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != "app" for alias in node.names), path.name


def test_frozen_constants_match_protocol_v1() -> None:
    assert LEDGER.genesis() == chain.genesis().public()
    assert tuple(LEDGER.PUBLICATION_TABLES) == events.PUBLICATION_KINDS
    assert LEDGER.SPECIALIST_PRIVATE == events.SPECIALIST_PRIVATE_FIELDS
    assert LEDGER.HOSPITAL_PRIVATE == events.HOSPITAL_PRIVATE_FIELDS


def test_frozen_canonical_json_and_commitments_match_the_shared_vectors() -> None:
    for vector in VECTORS["valid"]:
        if not any(isinstance(v, float) for v in _leaves(vector["value"])):
            assert LEDGER.canonical(vector["value"]) == vector["canonical"], vector["name"]
    for c in VECTORS["commitments"]:
        assert LEDGER.commitment(c["salt"], c["subject"], c["field"], c["value"]) == c["commitment"]


def _leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


def test_frozen_builders_agree_with_the_application_byte_for_byte() -> None:
    for kind, rows in PUBLICATIONS.items():
        for row in rows:
            event = events.published(kind, row)
            assert LEDGER.published(kind, row) == (event.created_at, event.subject, event.payload)
    for row in SPECIALIST:
        salt = SALTS[f"specialist_decision:{row['id']}"]
        for seq in (None, 7):
            event = events.specialist_decision(row, salt, seq)
            frozen = LEDGER.specialist_decision(row, salt, seq)
            assert (frozen[0], frozen[1], canonical_text(frozen[2])) == (
                event.created_at,
                event.subject,
                canonical_text(event.payload),
            )
    for row in HOSPITAL:
        event = events.hospital_decision(row, SALTS[f"hospital_decision:{row['id']}"])
        frozen = LEDGER.hospital_decision(row, SALTS[f"hospital_decision:{row['id']}"])
        assert (frozen[0], frozen[1], canonical_text(frozen[2])) == (
            event.created_at,
            event.subject,
            canonical_text(event.payload),
        )


def test_frozen_backfill_is_a_valid_chain_that_the_application_can_extend() -> None:
    entries = [chain.entry_from_public(e) for e in _frozen()]
    assert chain.verify_chain(entries).ok
    # every entry re-hashed by the application's own code
    for entry in entries:
        assert (
            chain.make_entry(
                entry.seq, entry.created_at, entry.event_type, entry.subject, entry.payload, entry.prev_hash
            )
            == entry
        )
    kinds = [e.payload.get("publication_kind") or e.payload.get("decision_kind") for e in entries[1:]]
    assert kinds == [
        "operational_intelligence",  # the day before
        "specialist_decision",  # one microsecond before T0
        *events.PUBLICATION_KINDS,  # T0, in rank order
        "hospital_decision",
        "specialist_decision",
    ]
    # the decision links to the entry of the operational publication active when it was written
    assert entries[-1].payload["evidence"]["operational_publication_ledger_seq"] == entries[4].seq


def test_the_frozen_backfill_never_changes() -> None:
    assert _frozen()[-1]["entry_hash"] == GOLDEN_BACKFILL_HEAD


def test_the_golden_chain_is_what_the_current_builders_state() -> None:
    """docs/transparency-ledger-vectors.json "chain" is derived from its "chain_source" rows by protocol v1 exactly:
    the browser and the offline verifier are tested against the payloads the server really writes."""
    entries = [chain.genesis()]
    for item in VECTORS["chain_source"]:
        row = dict(item["row"])
        for key in ("published_at", "created_at"):
            if key in row:
                row[key] = dt.datetime.fromisoformat(row[key].replace("Z", "+00:00"))
        if "origin" in row:
            row["origin"] = dt.date.fromisoformat(row["origin"])
        if item["kind"] == "hospital_decision":
            event = events.hospital_decision(row, item["salt"])
        elif item["kind"] == "specialist_decision":
            event = events.specialist_decision(row, item["salt"], item["operational_publication_ledger_seq"])
        else:
            event = events.published(item["kind"], row)
        entries.append(events.chain_next(entries[-1], event))
    assert [e.public() for e in entries] == VECTORS["chain"]
    kinds = {e.payload.get("publication_kind") for e in entries} - {None}
    assert {"referral_estimates", "verification_worklist"} <= kinds
