"""Small contract tests for reproducible ML runs; no model fitting or database access."""

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))

from hqai_ml.evaluation.protocol import TemporalProtocol  # noqa: E402
from hqai_ml.registry import store  # noqa: E402
from hqai_ml.registry.experiment import (  # noqa: E402
    CheckpointIncompatibleError,
    ExperimentRun,
    assert_safe_metadata,
    yaml_identity,
)
from hqai_ml.registry.resources import resource_config  # noqa: E402


def artifact(directory: Path) -> dict:
    directory.mkdir(parents=True)
    (directory / "model.txt").write_text("tiny model", encoding="utf-8")
    return store.write_artifact_manifest(directory)


def plan(identity: str = "plan-a") -> dict:
    return {
        "identity_sha256": identity,
        "models": ["wait_time"],
        "model_families": {"wait_time": "test_family"},
        "prediction_targets": {"wait_time": ["wait_days"]},
        "dataset": {"identity_sha256": "data-a"},
        "configuration": {"sha256": "config-a"},
        "code": {"source": {"sha256": "code-a"}},
    }


def temporal_protocol() -> TemporalProtocol:
    import datetime as dt

    return TemporalProtocol(
        train_start=dt.date(2025, 1, 1),
        train_end=dt.date(2025, 2, 28),
        validation_start=dt.date(2025, 2, 15),
        validation_end=dt.date(2025, 2, 28),
        test_start=dt.date(2025, 3, 1),
        test_end=dt.date(2025, 3, 31),
        forecast_origin=dt.date(2025, 3, 31),
        prediction_horizon_days=14,
        backtest_origins=(dt.date(2025, 3, 3), dt.date(2025, 3, 17)),
        label_availability_rule="observed after the origin",
        feature_availability_cutoff="no later than the origin",
        leakage_exclusions=("future target",),
        warm_up_period=(dt.date(2025, 1, 1), dt.date(2025, 1, 31)),
    )


def test_run_manifest_serialization_is_deterministic():
    left = {"z": [3, 2], "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "z": [3, 2]}
    assert store.canonical_json(left) == store.canonical_json(right)
    assert store.canonical_json(left).endswith("\n")


def test_yaml_order_does_not_change_config_identity_but_values_do(tmp_path: Path):
    config = tmp_path / "models.yaml"
    config.write_text("alpha: 1\nnested:\n  x: 2\n  y: 3\n", encoding="utf-8")
    first = yaml_identity([config], tmp_path)["sha256"]
    config.write_text("nested:\n  y: 3\n  x: 2\nalpha: 1\n", encoding="utf-8")
    reordered = yaml_identity([config], tmp_path)["sha256"]
    config.write_text("nested:\n  y: 4\n  x: 2\nalpha: 1\n", encoding="utf-8")
    changed = yaml_identity([config], tmp_path)["sha256"]
    assert first == reordered
    assert first != changed


def test_artifact_sha256_and_corruption_rejection(tmp_path: Path):
    path = tmp_path / "artifact"
    manifest = artifact(path)
    assert store.sha256_file(path / "model.txt") == hashlib.sha256(b"tiny model").hexdigest()
    assert store.verify_artifact_manifest(path) == manifest

    (path / "model.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(store.ArtifactIntegrityError, match="checksum mismatch"):
        store.verify_artifact_manifest(path)


def test_current_pointer_rejects_replaced_artifact_identity(tmp_path: Path):
    path = tmp_path / "models" / "wait_time" / "v1"
    artifact(path)
    store.atomic_write_text(
        tmp_path / "models" / "manifest.json",
        store.canonical_json(
            {
                "wait_time": {
                    "current": "v1",
                    "path": "models/wait_time/v1",
                    "artifact_sha256": "not-the-registered-identity",
                }
            }
        ),
    )
    with pytest.raises(store.ArtifactIntegrityError, match="current pointer checksum mismatch"):
        store.load(tmp_path, "wait_time")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"train_end": "test_start"}, "training must end"),
        ({"backtest_origins": "after_test"}, "inside the test period"),
        ({"prediction_horizon_days": 30}, "extends past the test period"),
    ],
)
def test_temporal_protocol_rejects_invalid_or_future_splits(changes: dict, message: str):
    import datetime as dt

    valid = temporal_protocol()
    resolved = {
        key: (valid.test_start if value == "test_start" else (dt.date(2025, 4, 1),) if value == "after_test" else value)
        for key, value in changes.items()
    }
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(valid, **resolved).validate()


def test_temporal_protocol_accepts_ordered_backtests():
    temporal_protocol().validate()


def test_incomplete_checkpoint_is_not_reused(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, plan(), run_id="interrupted")
    run.start_checkpoint("wait_time")
    assert run.reusable_checkpoint("wait_time") is None


def test_completed_checkpoint_is_reusable_on_resume(tmp_path: Path):
    model_path = tmp_path / "models" / "wait_time" / "v1"
    checksum = artifact(model_path)["content_sha256"]
    run = ExperimentRun.start(tmp_path, plan(), run_id="resumable")
    run.start_checkpoint("wait_time")
    run.complete_checkpoint(
        "wait_time",
        artifact_path=model_path,
        artifact_sha256=checksum,
        version="v1",
        metrics={"mae": 1.0},
        baseline_metrics={"median": {"mae": 2.0}},
    )

    resumed = ExperimentRun.start(tmp_path, plan(), resume_run_id="resumable")
    assert resumed.reusable_checkpoint("wait_time")["artifact"]["sha256"] == checksum


def test_resume_and_checkpoint_reject_incompatible_identity(tmp_path: Path):
    model_path = tmp_path / "models" / "wait_time" / "v1"
    checksum = artifact(model_path)["content_sha256"]
    run = ExperimentRun.start(tmp_path, plan(), run_id="identity-check")
    run.start_checkpoint("wait_time")
    run.complete_checkpoint(
        "wait_time",
        artifact_path=model_path,
        artifact_sha256=checksum,
        version="v1",
        metrics={"mae": 1.0},
        baseline_metrics={},
    )
    run.manifest["checkpoints"]["wait_time"]["identity_sha256"] = "wrong"
    with pytest.raises(CheckpointIncompatibleError, match="checkpoint"):
        run.reusable_checkpoint("wait_time")
    with pytest.raises(CheckpointIncompatibleError, match="resume rejected"):
        ExperimentRun.start(tmp_path, plan("plan-b"), resume_run_id="identity-check")


def test_registration_requires_a_completed_consistent_run(tmp_path: Path):
    model_path = tmp_path / "models" / "wait_time" / "v1"
    checksum = artifact(model_path)["content_sha256"]
    run = ExperimentRun.start(tmp_path, plan(), run_id="registration")
    run.start_checkpoint("wait_time")
    run.complete_checkpoint(
        "wait_time",
        artifact_path=model_path,
        artifact_sha256=checksum,
        version="v1",
        metrics={"mae": 1.0},
        baseline_metrics={},
    )
    loaded = {
        "path": model_path,
        "version": "v1",
        "artifact_sha256": checksum,
        "artifact_manifest": store.verify_artifact_manifest(model_path),
        "metrics": {"overall": [{"mae": 1.0}]},
        "meta": {
            "model_name": "wait_time",
            "training_window": {"train": ["2025-01-01", "2025-02-28"]},
            "run_id": "registration",
            "dataset_identity": "data-a",
            "config_identity": "config-a",
            "code_identity": "code-a",
            "evaluation_status": "passed",
            "model_family": "test_family",
            "target": "wait_days",
        },
    }
    with pytest.raises(store.ArtifactIntegrityError, match="conflicts with its run manifest"):
        store.registration_evidence(loaded)
    run.complete()
    assert store.registration_evidence(loaded)["lineage"] == "complete"


@pytest.mark.parametrize("profile", ["laptop", "overnight"])
def test_resource_profiles_bound_parallelism(profile: str):
    resources = resource_config(profile, cpu_count=10, model_threads=100, parallel_trials=100, process_concurrency=100)
    assert 1 <= resources.model_threads <= 10
    assert 1 <= resources.parallel_trials <= 10
    assert 1 <= resources.process_concurrency <= 10
    if profile == "laptop":
        defaults = resource_config(profile, cpu_count=10)
        assert defaults.model_threads == 4
        assert defaults.parallel_trials == defaults.process_concurrency == 1


def test_persisted_metadata_has_no_absolute_path_or_secret(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, plan(), run_id="safe-metadata")
    persisted = run.manifest_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in persisted
    assert "password" not in persisted
    assert json.loads(persisted)["run_id"] == "safe-metadata"
    with pytest.raises(ValueError, match="absolute local path"):
        assert_safe_metadata({"artifact": "/tmp/private/model.txt"})
    with pytest.raises(ValueError, match="sensitive field"):
        assert_safe_metadata({"api_token": "do-not-persist"})
