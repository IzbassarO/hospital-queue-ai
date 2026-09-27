"""Focused contract checks for migration 0012: specialist decisions carry the operational publication identity."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import SpecialistDecision

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0012_specialist_decision_publication.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0012", MIGRATION)
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

    def drop_column(self, table, name):
        self.dropped.append((table, name))


def test_upgrade_adds_the_nullable_column_the_model_declares() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    assert migration.revision == "0012" and migration.down_revision == "0011"
    assert [table for table, _ in recorder.added] == ["specialist_decision"]
    column = recorder.added[0][1]
    model_column = SpecialistDecision.__table__.columns["publication_identity_sha256"]
    assert isinstance(column, sa.Column) and column.name == model_column.name
    assert column.nullable and model_column.nullable
    assert isinstance(column.type, sa.String) and column.type.length == model_column.type.length == 64


def test_downgrade_drops_exactly_that_column() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped == [("specialist_decision", "publication_identity_sha256")]
