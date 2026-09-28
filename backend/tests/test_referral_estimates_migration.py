"""Focused contract checks for referral-estimates migration 0016 (no database needed)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import ReferralEstimate, ReferralEstimateSnapshot

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0016_referral_estimates_read_model.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0016", MIGRATION)
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
    assert migration.revision == "0016" and migration.down_revision == "0015"
    expected = {
        "referral_estimate_snapshot": ReferralEstimateSnapshot,
        "referral_estimate": ReferralEstimate,
    }
    assert set(recorder.tables) == set(expected)
    for table_name, model in expected.items():
        migration_columns = {column.name for column in recorder.tables[table_name] if isinstance(column, sa.Column)}
        assert migration_columns == {column.name for column in model.__table__.columns}


def test_only_one_publication_can_be_active() -> None:
    assert any(
        name == "ux_referral_estimate_snapshot_active" and kwargs["unique"]
        for name, _, _, kwargs in upgraded().created_indexes
    )


def test_the_refusal_follow_up_order_is_indexed() -> None:
    """The administrative order of one hospital's queue must not sort the whole publication."""
    assert any(
        columns == ("snapshot_id", "org_code", "refused_30d")
        for _, table, columns, _ in upgraded().created_indexes
        if table == "referral_estimate"
    )


def test_estimates_are_a_separate_table_from_the_measured_queue() -> None:
    """The measured publication keeps its own tables: no migration here touches waiting_list_*."""
    recorder = upgraded()
    assert not any(name.startswith("waiting_list") for name in recorder.tables)
    assert not any(table.startswith("waiting_list") for _, table, _, _ in recorder.created_indexes)


def test_downgrade_removes_children_before_snapshot() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == ["referral_estimate", "referral_estimate_snapshot"]
