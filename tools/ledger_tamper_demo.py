#!/usr/bin/env python3
"""Thirty-second tamper demonstration of the transparency ledger, on a database it creates and drops itself.

    make ledger-demo                 # creates hqai_tamper_demo_<random>, runs both attacks, drops it
    make ledger-demo KEEP=1          # keeps the tampered database and prints how to point the UI at it

It never touches the database in .env: it asks that server for a new, empty database (the role needs CREATEDB),
migrates it with Alembic, and does everything there.

Demo A — a covered source field changed behind the application's back:
  1. a specialist records a decision through the normal service; the receipt is printed;
  2. the decision's comment is rewritten with a plain SQL UPDATE, bypassing the application;
  3. the public chain still verifies (nothing in the ledger changed) — the offline verifier cannot see this, by
     design: it has no salts and no database;
  4. the server verification reports BROKEN at that entry: COMMITMENT_MISMATCH, with the subject.

Demo B — a historical entry changed in an exported copy:
  1. the public ledger is exported to JSONL;
  2. one old entry is edited in the copy (decline → accept);
  3. tools/ledger_verify.py reports BROKEN, the entry number and ENTRY_HASH_MISMATCH.

It also shows that the ledger table itself refuses UPDATE. docs/transparency-ledger.md §10.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.schemas.specialist import SpecialistDecisionCreate  # noqa: E402
from app.services import specialist_decisions, transparency  # noqa: E402

VERIFY = ROOT / "tools" / "ledger_verify.py"


def say(text: str = "") -> None:
    print(text, flush=True)


def step(title: str) -> None:
    say(f"\n── {title}")


def decision(action: str, comment: str) -> SpecialistDecisionCreate:
    return SpecialistDecisionCreate(
        origin="2025-03-17",
        run_id="tamper-demo",
        sim_day=2,
        subject_kind="alert",
        subject_id=f"signal-{uuid.uuid4().hex[:6]}",
        region_code="39",
        org_code="000V",
        profile_code="391",
        action=action,
        comment=comment,
        actor="Иванова А. (демо)",
        idempotency_key=f"tamper-demo-{uuid.uuid4()}",
    )


def server_report(factory) -> str:
    with factory() as session:
        report = transparency.verify(session)
    if report.status == "OK":
        return f"OK · проверено записей: {report.verified_through_seq} из {report.chain_length}"
    return f"BROKEN · запись №{report.failure_seq} · {report.reason_code} · {report.subject}"


def offline_report(path: Path) -> tuple[int, str]:
    run = subprocess.run([sys.executable, str(VERIFY), str(path)], capture_output=True, text=True)
    lines = run.stdout.splitlines()
    if run.returncode == 0:
        return 0, f"{lines[0]} · {lines[1]}"
    return run.returncode, " · ".join(lines[:3])


def export(factory, path: Path) -> None:
    with factory() as session:
        path.write_text("".join(transparency.export_lines(session)), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--keep", action="store_true", help="keep the tampered database for the UI")
    args = parser.parse_args()

    settings = get_settings()
    name = f"hqai_tamper_demo_{uuid.uuid4().hex[:8]}"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except DBAPIError as exc:
        say(f"cannot create a throwaway database ({exc.orig}); the role in .env needs CREATEDB")
        return 2
    engine = create_engine(make_url(settings.database_url).set(database=name))
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    keep = args.keep
    try:
        say(f"Изолированная база: {name} (рабочая база из .env не затрагивается)")
        migrate = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env={**os.environ, "POSTGRES_DB": name},
            capture_output=True,
            text=True,
        )
        if migrate.returncode != 0:
            say(migrate.stderr[-2000:])
            return 2

        step("Специалист принимает решения обычным путём")
        receipts = []
        for action, comment in (
            ("decline", "Отказ: мест нет, направить в соседний стационар"),
            ("accept", "Согласовано с приёмным отделением"),
            ("clarify", "Уточнить у заведующего"),
        ):
            with factory() as session:
                made, _ = specialist_decisions.create_decision(session, decision(action, comment), "демо-ключ")
            receipts.append(made)
            say(
                f"  решение #{made.id} «{action}» → запись журнала №{made.receipt.ledger_seq}, "
                f"SHA-256 {made.receipt.entry_hash[:12]}…"
            )
        say(f"  серверная проверка: {server_report(factory)}")

        step("Журнал сам по себе не изменить")
        try:
            with engine.begin() as conn:
                conn.execute(text("UPDATE transparency_ledger SET payload = '{}' WHERE seq = 2"))
        except DBAPIError as exc:
            say(f"  UPDATE transparency_ledger → отказ базы: {str(exc.orig).splitlines()[0]}")

        target = receipts[1]
        step(f"Демо A: тихо меняем комментарий решения #{target.id} в обход приложения")
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE specialist_decision SET comment = :c WHERE id = :i"),
                {"c": "Отказ согласован заранее", "i": target.id},
            )
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp) / "ledger.jsonl"
            export(factory, public)
            code, text_ = offline_report(public)
            say(f"  независимая проверка публичной цепочки: {text_}")
            say("    (публичный журнал не менялся — без соли и без базы подмену строки не увидеть)")
            say(f"  серверная проверка: {server_report(factory)}")

            step("Демо B: правим старую запись в выгруженной копии журнала")
            first = receipts[0].receipt.ledger_seq
            lines = public.read_text(encoding="utf-8").splitlines(keepends=True)
            lines[first - 1] = lines[first - 1].replace('"action":"decline"', '"action":"accept"')
            edited = Path(tmp) / "ledger-edited.jsonl"
            edited.write_text("".join(lines), encoding="utf-8")
            say(f"  в копии запись №{first}: decline → accept")
            code, text_ = offline_report(edited)
            say(f"  tools/ledger_verify.py: {text_} (код выхода {code})")

        say("\nИтог: модель предупреждает, решает человек — и что было решено, проверяемо.")
        if keep:
            say(
                f"\nБаза сохранена: {name}. Посмотреть BROKEN в интерфейсе: POSTGRES_DB={name} make api-dev, "
                f"затем открыть /verify. Удалить: psql -c 'DROP DATABASE \"{name}\"'"
            )
        return 0
    finally:
        engine.dispose()
        if not keep:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


if __name__ == "__main__":
    sys.exit(main())
