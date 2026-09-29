"""Publication events are written live, in the publish transaction: published + activated for a new snapshot,
deactivated for the one it replaces, nothing for an idempotent republish of the active one, and a re-activation when
an older publication is published again. Runs inside `ledger_isolation` (via preserve_current_snapshot)."""

from __future__ import annotations

from sqlalchemy import select

import test_operational_intelligence as oi_tests
from app.db.models import TransparencyLedger
from app.domain.transparency import chain
from app.services import operational_intelligence, transparency
from test_operational_intelligence import (
    _bundle,
    _parsed,
    preserve_current_snapshot,  # noqa: F401 - imported pytest fixture: isolation + synthetic assurance
)


def _new_entries(since: int) -> list[tuple[str, str]]:
    with oi_tests.SessionLocal() as session:
        rows = session.scalars(
            select(TransparencyLedger).where(TransparencyLedger.seq > since).order_by(TransparencyLedger.seq)
        )
        return [(row.event_type, row.subject) for row in rows]


def _head() -> int:
    with oi_tests.SessionLocal() as session:
        return transparency.head(session).seq


def test_publication_lifecycle_is_recorded_live() -> None:
    first = _bundle()
    second = _bundle()
    subject = lambda payload: f"publication:operational_intelligence:{payload['publication_id']}"  # noqa: E731

    with oi_tests.SessionLocal() as session:
        previous = operational_intelligence.repository.current_snapshot(session)
        previous_subject = (
            f"publication:operational_intelligence:{previous.publication_id}" if previous is not None else None
        )
    start = _head()
    with oi_tests.SessionLocal() as session:
        operational_intelligence.publish(session, _parsed(first))
    expected = [("publication.published", subject(first)), ("publication.activated", subject(first))]
    if previous_subject:
        expected.insert(0, ("publication.deactivated", previous_subject))
    assert _new_entries(start) == expected

    mark = _head()
    with oi_tests.SessionLocal() as session:
        replay = operational_intelligence.publish(session, _parsed(first))
    assert not replay.created
    assert _new_entries(mark) == []  # already active: nothing happened, nothing is claimed

    mark = _head()
    with oi_tests.SessionLocal() as session:
        operational_intelligence.publish(session, _parsed(second))
    assert _new_entries(mark) == [
        ("publication.deactivated", subject(first)),
        ("publication.published", subject(second)),
        ("publication.activated", subject(second)),
    ]

    mark = _head()
    with oi_tests.SessionLocal() as session:
        operational_intelligence.publish(session, _parsed(first))  # back to the first: a re-activation
    assert _new_entries(mark) == [
        ("publication.deactivated", subject(second)),
        ("publication.activated", subject(first)),
    ]

    with oi_tests.SessionLocal() as session:
        report = transparency.verify(session)
        entries = [transparency._entry(row) for row in transparency.repository.iterate(session)]
    assert chain.verify_chain(entries).ok
    # the fixture inserts its assurance snapshot straight into the table, bypassing publish: the server verifier
    # reports exactly that row, and nothing else
    assert {(i.reason_code, i.subject) for i in report.issues} <= {
        ("UNCOVERED_SOURCE_ROW", f"publication:model_assurance:{oi_tests.TEST_PREFIX}assurance")
    }
