"""Focused contract checks for operational-intelligence migration 0008."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import OperationalForecast, OperationalIntelligenceSnapshot, OperationalSignal

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0008_operational_intelligence_read_model.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0008", MIGRATION)
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
    assert migration.revision == "0008" and migration.down_revision == "0007"
    expected = {
        "operational_intelligence_snapshot": OperationalIntelligenceSnapshot,
        "operational_forecast": OperationalForecast,
        "operational_signal": OperationalSignal,
    }
    assert set(recorder.tables) == set(expected)
    for table_name, model in expected.items():
        migration_columns = {column.name for column in recorder.tables[table_name] if isinstance(column, sa.Column)}
        assert migration_columns == {column.name for column in model.__table__.columns}
    assert any(
        name == "ux_operational_intelligence_snapshot_active" and kwargs["unique"]
        for name, _, _, kwargs in recorder.created_indexes
    )


def test_downgrade_removes_children_before_snapshot() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == [
        "operational_signal",
        "operational_forecast",
        "operational_intelligence_snapshot",
    ]
