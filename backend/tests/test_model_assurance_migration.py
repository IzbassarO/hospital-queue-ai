"""Focused contract checks for migration 0007 and its SQLAlchemy models."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import ModelAssuranceCapability, ModelAssuranceSnapshot

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0007_model_assurance_read_model.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0007", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOp:
    def __init__(self):
        self.tables = {}
        self.created_indexes = []
        self.dropped_indexes = []
        self.dropped_tables = []

    def create_table(self, name, *items):
        self.tables[name] = items

    def create_index(self, name, table, columns, **kwargs):
        self.created_indexes.append((name, table, tuple(columns), kwargs))

    def drop_index(self, name, **kwargs):
        self.dropped_indexes.append((name, kwargs))

    def drop_table(self, name):
        self.dropped_tables.append(name)


def test_migration_and_models_define_the_same_read_model_tables() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()

    assert migration.revision == "0007"
    assert migration.down_revision == "0006"
    assert set(recorder.tables) == {"model_assurance_snapshot", "model_assurance_capability"}
    assert {column.name for column in recorder.tables["model_assurance_snapshot"] if isinstance(column, sa.Column)} == {
        column.name for column in ModelAssuranceSnapshot.__table__.columns
    }
    assert {
        column.name for column in recorder.tables["model_assurance_capability"] if isinstance(column, sa.Column)
    } == {column.name for column in ModelAssuranceCapability.__table__.columns}
    assert any(
        name == "ux_model_assurance_snapshot_active" and kwargs["unique"]
        for name, _, _, kwargs in recorder.created_indexes
    )


def test_migration_downgrade_removes_capabilities_before_snapshots() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == ["model_assurance_capability", "model_assurance_snapshot"]
