"""Transparency ledger (docs/transparency-ledger.md): database guarantees, concurrency, deterministic backfill, privacy,
server verification and the tamper cases, each on a throwaway database this module creates and drops.

The throwaway databases are migrated by Alembic in a subprocess (the same `alembic upgrade` operators run), so the
triggers, indexes and backfill under test are the migration's own. The role running the tests must be allowed to
CREATE DATABASE (CI's is); without that the module is skipped with the reason.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import SpecialistDecision, TransparencyLedger
from app.domain.transparency import chain, events
from app.domain.transparency.canonical import canonical_text, parse_timestamp
from app.schemas.activity import DecisionCreate
from app.schemas.specialist import SpecialistDecisionCreate
from app.services import specialist_decisions, transparency

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(ROOT / "tools"))
import ledger_verify  # noqa: E402 - the standalone verifier, imported from tools/

SETTINGS = get_settings()


# ------------------------------------------------------------------------------------------------ throwaway databases
def _admin_engine() -> Engine:
    return create_engine(SETTINGS.database_url, isolation_level="AUTOCOMMIT")


def _alembic(database: str, *args: str) -> None:
    env = {**os.environ, "POSTGRES_DB": database}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr[-3000:]


@contextmanager
def throwaway_database(revision: str = "head") -> Iterator[Engine]:
    name = f"hqai_ledger_test_{uuid.uuid4().hex[:10]}"
    admin = _admin_engine()
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except DBAPIError as exc:
        admin.dispose()
        pytest.skip(f"cannot create a throwaway database: {exc.orig}")
    url = make_url(SETTINGS.database_url).set(database=name)
    engine = create_engine(url)
    try:
        _alembic(name, "upgrade", revision)
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="module")
def ledger_db() -> Iterator[Engine]:
    with throwaway_database() as engine:
        yield engine


@pytest.fixture
def db(ledger_db: Engine) -> Iterator[sessionmaker]:
    yield sessionmaker(bind=ledger_db, autoflush=False, expire_on_commit=False)


def _decision_payload(**overrides) -> SpecialistDecisionCreate:
    values = {
        "origin": "2025-03-17",
        "run_id": f"run-{uuid.uuid4().hex[:6]}",
        "sim_day": 1,
        "subject_kind": "alert",
        "subject_id": f"signal-{uuid.uuid4().hex[:6]}",
        "region_code": "39",
        "org_code": "000V",
        "profile_code": "391",
        "action": "accept",
        "comment": "Согласовано с приёмным отделением",
        "actor": "Иванова А.",
        "idempotency_key": f"pytest-{uuid.uuid4()}",
    }
    values.update(overrides)
    return SpecialistDecisionCreate(**values)


def _chain(engine: Engine) -> list[chain.LedgerEntry]:
    with Session(engine) as session:
        return [transparency._entry(row) for row in session.query(TransparencyLedger).order_by(TransparencyLedger.seq)]


def _export(engine: Engine) -> str:
    with Session(engine) as session:
        return "".join(transparency.export_lines(session))


def _verify(engine: Engine):
    with Session(engine) as session:
        return transparency.verify(session)


# ------------------------------------------------------------------------------------------------ database guarantees
def test_genesis_is_the_protocol_constant(ledger_db: Engine) -> None:
    first = _chain(ledger_db)[0]
    assert first == chain.genesis()
    assert first.created_at == chain.GENESIS_CREATED_AT and first.prev_hash == chain.ZERO_HASH


def test_decision_appends_one_linked_entry_and_a_receipt(db: sessionmaker, ledger_db: Engine) -> None:
    before = _chain(ledger_db)
    with db() as session:
        decision, created = specialist_decisions.create_decision(session, _decision_payload(), "pytest-label")
    after = _chain(ledger_db)
    assert created and len(after) == len(before) + 1
    entry = after[-1]
    assert entry.prev_hash == before[-1].entry_hash
    assert decision.receipt is not None
    assert (decision.receipt.ledger_seq, decision.receipt.entry_hash) == (entry.seq, entry.entry_hash)
    assert entry.subject == f"specialist_decision:{decision.id}" and entry.event_type == "decision.recorded"
    assert decision.receipt.verify_path == f"/verify?seq={entry.seq}"


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE transparency_ledger SET subject = 'x' WHERE seq = 1",
        "DELETE FROM transparency_ledger WHERE seq = 1",
        "TRUNCATE transparency_ledger",
        "UPDATE transparency_commitment_salt SET salt = repeat('0', 64)",
        "DELETE FROM transparency_commitment_salt",
        "TRUNCATE transparency_commitment_salt",
    ],
)
def test_ledger_and_salts_reject_update_delete_truncate(ledger_db: Engine, statement: str) -> None:
    # a row trigger fires only on rows that exist: make sure the salt table has one (INSERT is allowed)
    with ledger_db.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transparency_commitment_salt (subject, salt) VALUES ('pytest:trigger', repeat('c', 64)) "
                "ON CONFLICT DO NOTHING"
            )
        )
    with ledger_db.connect() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text(statement))


def test_rollback_removes_the_decision_and_its_entry(db: sessionmaker, ledger_db: Engine) -> None:
    before = _chain(ledger_db)
    with db() as session:
        row = SpecialistDecision(
            origin=dt.date(2025, 3, 17),
            sim_day=0,
            subject_kind="alert",
            subject_id="rolled-back",
            action="accept",
            comment="never committed",
        )
        session.add(row)
        session.flush()
        receipt = transparency.record_specialist_decision(session, row)
        assert receipt.ledger_seq == before[-1].seq + 1
        session.rollback()
    assert _chain(ledger_db) == before
    with Session(ledger_db) as session:
        assert session.query(SpecialistDecision).filter_by(subject_id="rolled-back").count() == 0


def test_idempotent_retry_returns_the_original_receipt(db: sessionmaker, ledger_db: Engine) -> None:
    payload = _decision_payload()
    with db() as session:
        first, created = specialist_decisions.create_decision(session, payload, "pytest-label")
    length = len(_chain(ledger_db))
    with db() as session:
        again, replayed = specialist_decisions.create_decision(session, payload, "pytest-label")
    assert created and not replayed
    assert again.receipt == first.receipt
    assert len(_chain(ledger_db)) == length


def test_twenty_concurrent_decisions_form_one_chain(ledger_db: Engine) -> None:
    before = len(_chain(ledger_db))
    workers = 20
    # one connection per worker, so the only thing serializing them is the ledger's own advisory lock
    pool = create_engine(ledger_db.url, pool_size=workers, max_overflow=0)
    db = sessionmaker(bind=pool, autoflush=False, expire_on_commit=False)
    barrier = threading.Barrier(workers)
    receipts: list = []
    errors: list[BaseException] = []

    def work() -> None:
        try:
            with db() as session:
                barrier.wait(timeout=30)
                decision, _ = specialist_decisions.create_decision(session, _decision_payload(), "pytest-concurrent")
                receipts.append(decision.receipt)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert not errors, errors
    entries = _chain(ledger_db)
    assert len(entries) == before + workers
    assert [e.seq for e in entries] == list(range(1, len(entries) + 1))
    assert len({e.prev_hash for e in entries}) == len(entries)  # no two entries share a parent: no fork
    assert sorted(r.ledger_seq for r in receipts) == list(range(before + 1, before + workers + 1))
    assert chain.verify_chain(entries).ok
    assert _verify(ledger_db).status == "OK"
    pool.dispose()


def test_concurrent_retries_of_one_decision_append_once(db: sessionmaker, ledger_db: Engine) -> None:
    payload = _decision_payload()
    before = len(_chain(ledger_db))
    barrier = threading.Barrier(5)
    results: list = []

    def work() -> None:
        with db() as session:
            barrier.wait(timeout=30)
            results.append(specialist_decisions.create_decision(session, payload, "pytest-retry"))

    threads = [threading.Thread(target=work) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(results) == 5
    assert sum(created for _, created in results) == 1
    assert len({(d.id, d.receipt.entry_hash) for d, _ in results}) == 1
    assert len(_chain(ledger_db)) == before + 1


def test_the_database_refuses_a_fork_even_without_the_lock(ledger_db: Engine) -> None:
    entries = _chain(ledger_db)
    head = entries[-1]
    rival = events.chain_next(
        entries[-2], events.Event("decision.recorded", "specialist_decision:999999", {"x": 1}, head.created_at)
    )
    with Session(ledger_db) as session, pytest.raises(IntegrityError):
        session.add(
            TransparencyLedger(
                seq=head.seq + 1,
                created_at=parse_timestamp(rival.created_at),
                event_type=rival.event_type,
                subject=rival.subject,
                payload=rival.payload,
                prev_hash=rival.prev_hash,  # same parent as the existing head: a fork
                entry_hash=rival.entry_hash,
            )
        )
        session.flush()


# ------------------------------------------------------------------------------------------------ privacy
def test_export_and_api_models_carry_no_salt_and_no_free_text(db: sessionmaker, ledger_db: Engine) -> None:
    secret_comment = f"Пациент Сейткали {uuid.uuid4().hex[:6]} — личное"
    with db() as session:
        decision, _ = specialist_decisions.create_decision(
            session, _decision_payload(comment=secret_comment, actor="Нұрлан Әбенов"), "УОЗ Астана, Иванова"
        )
    exported = _export(ledger_db)
    with Session(ledger_db) as session:
        salts = [row[0] for row in session.execute(text("SELECT salt FROM transparency_commitment_salt"))]
    assert salts
    for private in (secret_comment, "Нұрлан Әбенов", "УОЗ Астана, Иванова", decision.idempotency_key, *salts):
        assert private not in exported
    entry = next(e for e in _chain(ledger_db) if e.subject == f"specialist_decision:{decision.id}")
    assert set(entry.payload["commitments"]) == {"actor", "api_key_label", "comment", "idempotency_key"}


def test_commitments_separate_null_empty_and_changed_text() -> None:
    salt = "ab" * 32
    subject = "specialist_decision:1"
    values = [None, "", " ", "Да", "Да ", "да", "é", "é"]
    commitments = {chain.commitment(salt, subject, "comment", v) for v in values}
    assert len(commitments) == len(values)
    assert chain.commitment(salt, subject, "comment", "x") != chain.commitment("cd" * 32, subject, "comment", "x")
    assert chain.commitment(salt, subject, "comment", "x") != chain.commitment(salt, subject, "actor", "x")


# ------------------------------------------------------------------------------------------------ tampering (isolated)
def test_server_verifier_catches_source_row_tamper_that_the_public_chain_cannot() -> None:
    """Demo A: the public chain stays valid; only the verifier with the salts and the rows sees the change."""
    with throwaway_database() as engine:
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as session:
            decision, _ = specialist_decisions.create_decision(session, _decision_payload(), "pytest-tamper")
        seq = decision.receipt.ledger_seq
        assert _verify(engine).status == "OK"
        with engine.begin() as conn:  # bypasses the application: a silent edit of a covered field
            conn.execute(
                text("UPDATE specialist_decision SET comment = 'изменено задним числом' WHERE id = :i"),
                {"i": decision.id},
            )
        assert ledger_verify.verify_lines(_export(engine).splitlines(keepends=True))["entries"] == seq
        report = _verify(engine)
        assert (report.status, report.failure_seq, report.reason_code) == ("BROKEN", seq, "COMMITMENT_MISMATCH")
        assert report.subject == f"specialist_decision:{decision.id}"
        assert report.verified_through_seq == seq - 1
        assert "изменено" not in report.model_dump_json()

        with engine.begin() as conn:
            conn.execute(text("UPDATE specialist_decision SET action = 'decline' WHERE id = :i"), {"i": decision.id})
        assert _verify(engine).reason_code == "SOURCE_FIELD_MISMATCH"
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO specialist_decision (origin, sim_day, subject_kind, subject_id, action) "
                    "VALUES ('2025-03-17', 0, 'alert', 'smuggled', 'accept')"
                )
            )
        codes = {issue.reason_code for issue in _verify(engine).issues}
        assert {"SOURCE_FIELD_MISMATCH", "UNCOVERED_SOURCE_ROW"} <= codes
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM specialist_decision WHERE id = :i"), {"i": decision.id})
        assert _verify(engine).reason_code == "SOURCE_ROW_MISSING"


def test_offline_verifier_catches_an_edited_export(tmp_path: Path, db: sessionmaker, ledger_db: Engine) -> None:
    """Demo B: one historical entry changed in a copy of the export."""
    with db() as session:
        decision, _ = specialist_decisions.create_decision(session, _decision_payload(action="accept"), "pytest-b")
    lines = _export(ledger_db).splitlines(keepends=True)
    index = decision.receipt.ledger_seq - 1
    lines[index] = lines[index].replace('"action":"accept"', '"action":"decline"')
    edited = tmp_path / "edited.jsonl"
    edited.write_text("".join(lines), encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "ledger_verify.py"), str(edited)], capture_output=True, text=True
    )
    assert run.returncode == 1
    assert run.stdout.splitlines()[:3] == [
        "BROKEN",
        f"seq: {decision.receipt.ledger_seq}",
        "reason: ENTRY_HASH_MISMATCH",
    ]


# ------------------------------------------------------------------------------------------------ backfill
def _seed_rows_at_0015(engine: Engine) -> None:
    """Durable rows as the schema before the ledger holds them: two publication kinds, both decision tables, with
    equal timestamps across kinds to exercise the global order."""
    same = "2025-03-17 09:00:00+00"
    statements = [
        f"""INSERT INTO model_assurance_snapshot (assurance_id, contract_version, schema_version,
            assurance_identity_sha256, bundle_sha256, source_code_commit, ml_freeze_status, product_contract_version,
            generated_at, published_at, is_active, capability_count, failed_evidence_history, claim_boundaries,
            monitoring_expectations, freshness_policy)
            VALUES ('assurance-v1', '1.0.0', 'model_assurance_v1', repeat('a', 64), repeat('b', 64), repeat('1', 40),
            'ML_CORE_CLOSED_FROZEN', 'p1', NULL, '{same}', true, 0, '[]', '{{}}', '[]', '{{}}')""",
        *[
            f"""INSERT INTO operational_intelligence_snapshot (publication_id, schema_version, contract_version,
            publication_identity_sha256, bundle_sha256, assurance_identity_sha256, source_code_commit, current_origin,
            freshness_state, publication_status, generated_at, published_at, is_active, forecast_count, signal_count,
            source_provenance, limitations)
            VALUES ('oi-{i}', 'oi-v1', '1.0.0', repeat('{c}', 64), repeat('d', 64), repeat('a', 64), repeat('1', 40),
            '2025-03-17', 'FRESH', 'PUBLISHED', NULL, '{when}', {active}, 0, 0, '{{}}', '[]')"""
            for i, c, when, active in ((1, "e", "2025-03-16 08:00:00+00", "false"), (2, "f", same, "true"))
        ],
        f"""INSERT INTO decision_log (created_at, region_code, org_code, profile_code, action, comment, actor)
            VALUES ('{same}', '39', '000V', '391', 'defer', '', 'Дежурный врач'),
                   ('2025-03-18 10:00:00+05', '39', '000V', '391', 'confirm', NULL, 'Иванова')""",
        f"""INSERT INTO specialist_decision (created_at, origin, run_id, sim_day, subject_kind, subject_id, action,
            comment, actor, publication_identity_sha256)
            VALUES ('{same}', '2025-03-17', 'r1', 0, 'alert', 's-1', 'accept', 'Согласовано', 'Иванова',
                    repeat('f', 64)),
                   ('2025-03-17 08:59:59.999999+00', '2025-03-17', 'r1', 0, 'patient', 'Н-1', 'confirm', NULL, NULL,
                    NULL)""",
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))


def test_empty_database_gets_only_the_genesis() -> None:
    with throwaway_database() as engine:
        assert _chain(engine) == [chain.genesis()]
        assert _verify(engine).status == "OK"


def test_backfill_is_deterministic_ordered_and_invents_nothing() -> None:
    with throwaway_database("0015") as engine:
        _seed_rows_at_0015(engine)
        name = engine.url.database
        _alembic(name, "upgrade", "0016")
        with engine.connect() as conn:
            salts_before = dict(conn.execute(text("SELECT subject, salt FROM transparency_commitment_salt")).all())
        assert len(salts_before) == 4
        _alembic(name, "upgrade", "0017")
        first = _export(engine)
        entries = _chain(engine)

        # one global order: time, then rank (assurance < operational < hospital decision < specialist), then id
        assert [(e.event_type, e.subject.rsplit(":", 1)[0]) for e in entries] == [
            ("ledger.genesis", "ledger"),
            ("publication.published", "publication:operational_intelligence"),  # oi-1, the day before
            ("decision.recorded", "specialist_decision"),  # 08:59:59.999999, one microsecond earlier
            ("publication.published", "publication:model_assurance"),
            ("publication.published", "publication:operational_intelligence"),  # oi-2
            ("decision.recorded", "hospital_decision"),
            ("decision.recorded", "specialist_decision"),
            ("decision.recorded", "hospital_decision"),  # 10:00+05 = 05:00 UTC the next day
        ]
        # nothing about activation is invented: the rows do not say when anything became active
        assert not [e for e in entries if e.event_type in (events.ACTIVATED, events.DEACTIVATED)]
        # timestamps come from the rows, not from the migration's clock
        assert entries[5].created_at == "2025-03-17T09:00:00.000000Z"
        # the decision links to the entry of the publication that was active when it was written
        assert entries[6].payload["evidence"]["operational_publication_ledger_seq"] == entries[4].seq
        assert entries[5].payload["commitments"]["comment"] == chain.commitment(
            salts_before[entries[5].subject], entries[5].subject, "comment", ""
        )
        assert _verify(engine).status == "OK"

        # downgrade only the ledger, keep the salts, upgrade again: byte-identical
        _alembic(name, "downgrade", "0016")
        with engine.connect() as conn:
            assert dict(conn.execute(text("SELECT subject, salt FROM transparency_commitment_salt")).all()) == (
                salts_before
            )
        _alembic(name, "upgrade", "0017")
        assert _export(engine) == first
        assert ledger_verify.verify_lines(first.splitlines(keepends=True))["entries"] == len(entries)


# ------------------------------------------------------------------------------------------------ verifiers
VECTORS = __import__("json").loads((ROOT / "docs" / "transparency-ledger-vectors.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", VECTORS["valid"], ids=lambda v: v["name"])
def test_canonical_vectors_in_both_python_implementations(vector: dict) -> None:
    from app.domain.transparency.canonical import canonical_bytes

    assert canonical_text(vector["value"]) == vector["canonical"] == ledger_verify.canonical(vector["value"])
    assert __import__("hashlib").sha256(canonical_bytes(vector["value"])).hexdigest() == vector["sha256"]


@pytest.mark.parametrize("vector", VECTORS["invalid"], ids=lambda v: v["name"])
def test_invalid_vectors_rejected_with_the_shared_code(vector: dict) -> None:
    from app.domain.transparency.canonical import CanonicalError, parse_strict

    with pytest.raises(CanonicalError) as domain:
        parse_strict(vector["json"])
    with pytest.raises(ledger_verify.NotCanonical) as tool:
        ledger_verify.parse_strict(vector["json"])
    assert domain.value.code == tool.value.code == vector["error"]


def test_floats_and_foreign_types_never_reach_a_hash() -> None:
    from app.domain.transparency.canonical import CanonicalError

    for value in (1.0, float("nan"), dt.datetime.now(dt.UTC), b"x", {1: "a"}, {"A": 1}, "\ud800"):
        with pytest.raises(CanonicalError):
            canonical_text(value)


def test_golden_chain_and_commitments_match_the_vectors() -> None:
    entries = [chain.entry_from_public(e) for e in VECTORS["chain"]]
    assert chain.verify_chain(entries).ok
    assert VECTORS["genesis"] == chain.genesis().public()
    for c in VECTORS["commitments"]:
        assert chain.commitment(c["salt"], c["subject"], c["field"], c["value"]) == c["commitment"]


def _golden_lines() -> list[str]:
    return [ledger_verify.canonical(e) + "\n" for e in VECTORS["chain"]]


def _broken(lines: list[str], trusted=None) -> tuple[str, int | None]:
    with pytest.raises(ledger_verify.Broken) as exc:
        ledger_verify.verify_lines(lines, trusted)
    return exc.value.code, exc.value.seq


def _edit(index: int, change) -> list[str]:
    entries = [dict(e, payload=dict(e["payload"])) for e in VECTORS["chain"]]
    change(entries[index])
    return [ledger_verify.canonical(e) + "\n" for e in entries]


def test_offline_verifier_accepts_the_golden_chain() -> None:
    summary = ledger_verify.verify_lines(_golden_lines())
    assert summary == {
        "entries": len(VECTORS["chain"]),
        "head_seq": VECTORS["chain"][-1]["seq"],
        "head_hash": VECTORS["chain"][-1]["entry_hash"],
    }


def test_offline_verifier_failures() -> None:
    lines = _golden_lines()
    assert _broken(_edit(3, lambda e: e["payload"].update(action="decline"))) == ("ENTRY_HASH_MISMATCH", 4)
    assert _broken(_edit(2, lambda e: e.update(prev_hash="f" * 64))) == ("PREV_HASH_MISMATCH", 3)
    assert _broken([lines[0], *lines[2:]]) == ("SEQUENCE_GAP", 3)
    assert _broken([lines[0], lines[2], lines[1], lines[3]]) == ("SEQUENCE_GAP", 3)
    assert _broken([lines[0], lines[1], lines[1], *lines[2:]]) == ("DUPLICATE_SEQ", 2)
    assert _broken(lines, (2, "e" * 64)) == ("TRUSTED_HEAD_MISMATCH", 2)
    assert _broken(lines, (99, "e" * 64)) == ("TRUSTED_HEAD_MISSING", 99)
    assert _broken([lines[0], lines[1].replace('"snapshot_id":3', '"snapshot_id":3.0'), *lines[2:]])[0] == (
        "NONCANONICAL_VALUE"
    )
    assert _broken([lines[0].replace('{"created_at"', '{ "created_at"'), *lines[1:]])[0] == "NONCANONICAL_ENCODING"
    assert _broken(_edit(0, lambda e: e["payload"].update(protocol="other"))) == ("GENESIS_INVALID", 1)
    assert _broken([]) == ("EMPTY_LEDGER", None)
    assert ledger_verify.verify_lines(lines, (2, VECTORS["chain"][1]["entry_hash"]))["entries"] == 4


def test_offline_verifier_cli(tmp_path: Path) -> None:
    good = tmp_path / "ledger.jsonl"
    good.write_text("".join(_golden_lines()), encoding="utf-8")
    tool = [sys.executable, str(ROOT / "tools" / "ledger_verify.py")]
    ok = subprocess.run([*tool, str(good)], capture_output=True, text=True)
    assert ok.returncode == 0 and ok.stdout.startswith("VERIFIED\nentries: 4\n")
    head = VECTORS["chain"][-1]["entry_hash"]
    assert subprocess.run([*tool, str(good), "--expect-head", head], capture_output=True).returncode == 0
    assert subprocess.run([*tool, str(good), "--expect-head", "0" * 64], capture_output=True).returncode == 1
    assert subprocess.run([*tool, str(tmp_path / "missing.jsonl")], capture_output=True).returncode == 2


def test_server_and_domain_payload_builders_agree_with_the_migration(ledger_db: Engine) -> None:
    """What the live path writes is exactly what a backfill of the same rows states (same builders, same bytes)."""
    with Session(ledger_db) as session:
        rows = {row["id"]: row for row in transparency.repository.specialist_decisions(session)}
        salts = transparency.repository.all_salts(session)
    live = {e.subject: e for e in _chain(ledger_db) if e.subject.startswith("specialist_decision:")}
    assert live
    for subject, entry in live.items():
        row = rows[int(subject.split(":")[1])]
        rebuilt = events.specialist_decision(
            row, salts[subject], entry.payload["evidence"]["operational_publication_ledger_seq"]
        )
        assert canonical_text(rebuilt.payload) == canonical_text(entry.payload)
        assert rebuilt.created_at == entry.created_at


def test_decision_log_entries_are_verified_too(ledger_db: Engine) -> None:
    from app.db.models import DecisionLog

    payload = DecisionCreate(
        region_code="39", org_code="000V", profile_code="391", action="defer", comment="Ждём ответа", actor="Иванова"
    )
    with Session(ledger_db) as session:
        row = DecisionLog(**payload.model_dump(), api_key_label="pytest")
        session.add(row)
        session.flush()
        receipt = transparency.record_hospital_decision(session, row)
        session.commit()
    assert receipt.subject.startswith("hospital_decision:")
    assert _verify(ledger_db).status == "OK"
