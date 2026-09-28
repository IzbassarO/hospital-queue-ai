"""Focused contract checks for waiting-list migration 0014 (no database needed)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import WaitingListHospital, WaitingListReferral, WaitingListSnapshot

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0014_waiting_list_read_model.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0014", MIGRATION)
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


def test_migration_and_models_define_the_same_tables() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    assert migration.revision == "0014" and migration.down_revision == "0013"
    expected = {
        "waiting_list_snapshot": WaitingListSnapshot,
        "waiting_list_hospital": WaitingListHospital,
        "waiting_list_referral": WaitingListReferral,
    }
    assert set(recorder.tables) == set(expected)
    for table_name, model in expected.items():
        migration_columns = {column.name for column in recorder.tables[table_name] if isinstance(column, sa.Column)}
        assert migration_columns == {column.name for column in model.__table__.columns}


def test_only_one_publication_can_be_active() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    assert any(
        name == "ux_waiting_list_snapshot_active" and kwargs["unique"]
        for name, _, _, kwargs in recorder.created_indexes
    )


def test_referrals_are_indexed_for_the_by_days_waited_page() -> None:
    """The one read path that must not table-scan: one hospital's list ordered by days waited."""
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    assert any(
        columns == ("snapshot_id", "org_code", "days_waited_at_origin")
        for _, table, columns, _ in recorder.created_indexes
        if table == "waiting_list_referral"
    )


def test_downgrade_removes_children_before_snapshot() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == [
        "waiting_list_referral",
        "waiting_list_hospital",
        "waiting_list_snapshot",
    ]
