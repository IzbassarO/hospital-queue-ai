"""Focused schema-contract tests for nullable model-registry lineage."""

import importlib.util
from pathlib import Path

from app.db.models import ModelRegistry

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0006_model_registry_lineage.py"
LINEAGE_COLUMNS = {
    "run_id": 128,
    "artifact_sha256": 64,
    "dataset_identity": 64,
    "config_identity": 64,
    "code_identity": 64,
    "evaluation_status": 16,
}


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOp:
    def __init__(self):
        self.added = []
        self.dropped = []

    def add_column(self, table, column):
        self.added.append((table, column))

    def drop_column(self, table, column):
        self.dropped.append((table, column))


def test_migration_and_sqlalchemy_model_lineage_are_aligned():
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()

    assert migration.revision == "0006"
    assert migration.down_revision == "0005"
    assert {column.name: column.type.length for table, column in recorder.added if table == "model_registry"} == (
        LINEAGE_COLUMNS
    )
    for name, length in LINEAGE_COLUMNS.items():
        column = ModelRegistry.__table__.columns[name]
        assert column.nullable is True
        assert column.type.length == length


def test_migration_downgrade_removes_only_lineage_columns():
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert {name for table, name in recorder.dropped if table == "model_registry"} == set(LINEAGE_COLUMNS)


def test_legacy_registry_row_remains_readable_with_null_lineage():
    row = ModelRegistry(
        model_name="wait_time",
        version="legacy-v1",
        trained_at="2025-01-01T00:00:00",
        train_window={},
        metrics={},
        is_current=True,
        artifact_path="models/wait_time/legacy-v1",
        card=None,
    )
    assert all(getattr(row, name) is None for name in LINEAGE_COLUMNS)
