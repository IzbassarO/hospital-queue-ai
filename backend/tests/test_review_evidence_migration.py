"""Focused contract checks for review-evidence migration 0009."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.db.models import (
    ReviewAlternative,
    ReviewAlternativeSet,
    ReviewEvidenceSnapshot,
    ReviewScenario,
    ReviewScenarioCell,
    ReviewScenarioEntity,
)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "backend" / "alembic" / "versions" / "0009_review_evidence_read_model.py"


def load_migration():
    spec = importlib.util.spec_from_file_location("migration_0009", MIGRATION)
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


EXPECTED = {
    "review_evidence_snapshot": ReviewEvidenceSnapshot,
    "review_scenario": ReviewScenario,
    "review_scenario_entity": ReviewScenarioEntity,
    "review_scenario_cell": ReviewScenarioCell,
    "review_alternative_set": ReviewAlternativeSet,
    "review_alternative": ReviewAlternative,
}


def test_migration_and_models_define_the_same_tables() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.upgrade()
    assert migration.revision == "0009" and migration.down_revision == "0008"
    assert set(recorder.tables) == set(EXPECTED)
    for table_name, model in EXPECTED.items():
        columns = {column.name: column for column in recorder.tables[table_name] if isinstance(column, sa.Column)}
        assert set(columns) == {column.name for column in model.__table__.columns}, table_name
        for column in model.__table__.columns:
            assert columns[column.name].nullable == column.nullable, f"{table_name}.{column.name}"
    assert any(
        name == "ux_review_evidence_snapshot_active" and kwargs["unique"]
        for name, _, _, kwargs in recorder.created_indexes
    )
    assert any(name == "ix_review_scenario_entity_signal" for name, _, _, _ in recorder.created_indexes)


def test_downgrade_removes_children_before_snapshot() -> None:
    migration = load_migration()
    recorder = RecordingOp()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == [
        "review_alternative",
        "review_alternative_set",
        "review_scenario_cell",
        "review_scenario_entity",
        "review_scenario",
        "review_evidence_snapshot",
    ]
