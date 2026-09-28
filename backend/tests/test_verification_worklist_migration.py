"""Focused contract checks for verification-worklist migration 0017 (no database needed)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import (
    VerificationWorklistArea,
    VerificationWorklistItem,
    VerificationWorklistSnapshot,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0017_verification_worklist_read_model.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0017", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOp:
    def __init__(self):
        self.tables = {}
        self.created_indexes = []
        self.dropped_tables = []

    def create_table(self, name, *items):
        self.tables[name] = items

    def create_index(self, name, table, columns, **kwargs):
        self.created_indexes.append((name, table, tuple(columns), kwargs))

    def drop_index(self, name, **kwargs):
        pass

    def drop_table(self, name):
        self.dropped_tables.append(name)


def upgraded() -> RecordingOp:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    return recorder


def test_migration_and_models_define_the_same_tables() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    assert migration.revision == "0017" and migration.down_revision == "0016"
    expected = {
        "verification_worklist_snapshot": VerificationWorklistSnapshot,
        "verification_worklist_area": VerificationWorklistArea,
        "verification_worklist_item": VerificationWorklistItem,
    }
    assert set(recorder.tables) == set(expected)
    for table_name, model in expected.items():
        migration_columns = {column.name for column in recorder.tables[table_name] if isinstance(column, sa.Column)}
        assert migration_columns == {column.name for column in model.__table__.columns}


def test_only_one_publication_can_be_active() -> None:
    assert any(
        name == "ux_verification_worklist_snapshot_active" and kwargs["unique"]
        for name, _, _, kwargs in upgraded().created_indexes
    )


def test_the_hospital_page_is_indexed_by_the_published_rank() -> None:
    assert any(
        columns == ("snapshot_id", "org_code", "rank")
        for _, table, columns, _ in upgraded().created_indexes
        if table == "verification_worklist_item"
    )


def test_the_worklist_does_not_touch_the_measured_queue() -> None:
    """A review list may never migrate, index or otherwise reach into the publication it reviews."""
    recorder = upgraded()
    assert not any(name.startswith("waiting_list") for name in recorder.tables)
    assert not any(table.startswith("waiting_list") for _, table, _, _ in recorder.created_indexes)


def test_every_area_row_carries_its_own_denominator() -> None:
    """A warning count without formal_queue_count beside it is the number that gets misread."""
    columns = {
        column.name for column in upgraded().tables["verification_worklist_area"] if isinstance(column, sa.Column)
    }
    assert {"formal_queue_count", "history_quality_warning_count", "history_quality_warning_share"} <= columns


def test_an_item_row_has_no_column_for_an_outcome() -> None:
    """Origin-time rows only: the read model has nowhere to store what happened after the origin."""
    columns = {
        column.name for column in upgraded().tables["verification_worklist_item"] if isinstance(column, sa.Column)
    }
    assert not {name for name in columns if any(token in name for token in ("status", "outcome", "observed", "ghost"))}


def test_downgrade_removes_children_before_snapshot() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == [
        "verification_worklist_item",
        "verification_worklist_area",
        "verification_worklist_snapshot",
    ]
