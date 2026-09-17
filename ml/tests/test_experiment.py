"""Tiny experiment, checkpoint, registry, and resource contract tests; no model fitting."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
from pathlib import Path

import pytest

from hqai_ml.evaluation.protocol import TemporalProtocol
from hqai_ml.registry import experiment, store
from hqai_ml.registry.experiment import (
    CheckpointIncompatibleError,
    CheckpointKey,
    ExperimentRun,
    RunLock,
    RunLockedError,
    assert_safe_metadata,
    build_plan,
    execution_metadata,
    yaml_identity,
)
from hqai_ml.registry.resources import resource_config


def artifact(directory: Path) -> dict:
    directory.mkdir(parents=True)
    (directory / "model.txt").write_text("tiny model", encoding="utf-8")
    return store.write_artifact_manifest(directory)


def run_plan(profile: str = "laptop", identity: str = "plan-a", versions: dict | None = None) -> dict:
    resources = resource_config(profile, cpu_count=16)
    return {
        "scientific_identity_sha256": identity,
        "identity_sha256": identity,
        "scientific_identity": {"test": identity},
        "models": ["wait_time"],
        "model_families": {"wait_time": store.MODEL_CONTRACTS["wait_time"]["family"]},
        "prediction_targets": {"wait_time": store.MODEL_CONTRACTS["wait_time"]["prediction_targets"]},
        "dataset": {"identity_sha256": "data-a"},
        "configuration": {"sha256": "config-a"},
        "code": {"source": {"sha256": "code-a"}},
        "implementation_versions": versions or {"python": "3.12", "lightgbm": "4.7.0"},
        "execution": execution_metadata(resources),
    }


def temporal_protocol() -> TemporalProtocol:
    return TemporalProtocol(
        train_start=dt.date(2025, 1, 1),
        train_end=dt.date(2025, 2, 28),
        validation_start=dt.date(2025, 2, 15),
        validation_end=dt.date(2025, 2, 28),
        test_start=dt.date(2025, 3, 1),
        test_end=dt.date(2025, 3, 31),
        forecast_origin=dt.date(2025, 3, 31),
        origin_semantics="last_observed_day",
        prediction_horizon_days=14,
        backtest_origins=(dt.date(2025, 3, 2), dt.date(2025, 3, 16)),
        label_availability_rule="origin + 1 through origin + h",
        feature_availability_cutoff="no later than the origin",
        leakage_exclusions=("future target",),
        warm_up_period=None,
        warm_up_note="No rows are excluded.",
    )


def complete_artifact_checkpoint(
    run: ExperimentRun, root: Path, *, evaluated: bool = True
) -> tuple[CheckpointKey, Path, str]:
    key = CheckpointKey.model("wait_time")
    model_path = root / "models" / "wait_time" / "v1"
    checksum = artifact(model_path)["content_sha256"]
    run.start_checkpoint(key)
    run.complete_checkpoint(
        key,
        artifact_path=model_path,
        artifact_sha256=checksum,
        version="v1",
        metrics={"mae": 1.0},
        baseline_metrics={"median": {"mae": 2.0}},
        evaluation_status="completed" if evaluated else "pending",
    )
    return key, model_path, checksum


def test_canonical_serialization_is_deterministic():
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


def test_execution_profiles_and_threads_do_not_change_scientific_identity(tmp_path: Path, monkeypatch):
    configs = tmp_path / "configs"
    configs.mkdir()
    for name in ("models.yaml", "ingest.yaml", "explain_templates.yaml"):
        (configs / name).write_text("stable: true\n", encoding="utf-8")
    monkeypatch.setattr(experiment, "dataset_identity", lambda *_: {"identity_sha256": "data"})
    monkeypatch.setattr(
        experiment,
        "code_identity",
        lambda *_: {"source": {"sha256": "source"}, "git_commit": "abc", "dirty_worktree": False},
    )
    common = {
        "root": tmp_path,
        "processed_dir": tmp_path / "processed",
        "configs_dir": configs,
        "selected_models": ["wait_time"],
        "temporal_protocols": {"wait_time": {"split": "fixed"}},
        "versions": {"python": "3.12", "lightgbm": "4.7.0"},
    }
    laptop = build_plan(
        **common,
        resources=resource_config("laptop", cpu_count=16),
        hyperparameters={"lightgbm": {"seed": 42, "num_threads": 4, "force_row_wise": True}},
    )
    overnight = build_plan(
        **common,
        resources=resource_config("overnight", cpu_count=16),
        hyperparameters={"lightgbm": {"seed": 42, "num_threads": 8, "force_row_wise": True}},
    )
    assert laptop["scientific_identity_sha256"] == overnight["scientific_identity_sha256"]
    assert laptop["execution"] != overnight["execution"]
    assert "num_threads" not in laptop["hyperparameters"]["lightgbm"]


def test_resume_across_execution_profiles_reuses_checkpoint(tmp_path: Path):
    laptop = run_plan("laptop")
    run = ExperimentRun.start(tmp_path, laptop, run_id="cross-profile")
    key = CheckpointKey("wait_time", candidate_id="candidate-a", trial_id="trial-1", fold_id="fold-1")
    run.start_checkpoint(key, parameters={"learning_rate": 0.05})
    run.complete_checkpoint(
        key,
        parameters={"learning_rate": 0.05},
        metrics={"mae": 1.0},
        evaluation_status="completed",
    )
    run.pause()
    run.release_lock()

    overnight = run_plan("overnight")
    resumed = ExperimentRun.start(tmp_path, overnight, resume_run_id="cross-profile")
    try:
        assert laptop["scientific_identity_sha256"] == overnight["scientific_identity_sha256"]
        checkpoint = resumed.reusable_checkpoint(key, parameters={"learning_rate": 0.05})
        assert checkpoint is not None
        assert checkpoint["execution"]["resources"]["profile"] == "laptop"
        assert [item["resources"]["profile"] for item in resumed.manifest["executions"]] == [
            "laptop",
            "overnight",
        ]
    finally:
        resumed.release_lock()


def test_relevant_implementation_version_mismatch_rejects_resume(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, run_plan(identity="stack-a"), run_id="version-change")
    run.pause()
    run.release_lock()
    changed = run_plan(identity="stack-b", versions={"python": "3.12", "lightgbm": "4.8.0"})
    with pytest.raises(CheckpointIncompatibleError, match="implementation versions changed"):
        ExperimentRun.start(tmp_path, changed, resume_run_id="version-change")


@pytest.mark.parametrize("profile", ["laptop", "overnight"])
@pytest.mark.parametrize("cpu_count", [1, 2, 10])
def test_resource_profiles_honor_global_cpu_budget(profile: str, cpu_count: int):
    resources = resource_config(profile, cpu_count=cpu_count)
    assert resources.requested_cpu_slots <= resources.cpu_budget
    assert resources.cpu_budget <= resources.detected_cpu_count
    if cpu_count > 1:
        assert resources.cpu_budget < resources.detected_cpu_count


def test_resource_budget_derives_threads_and_rejects_oversubscription():
    derived = resource_config("overnight", cpu_count=16, parallel_trials=3, process_concurrency=2)
    assert derived.model_threads == 2
    assert derived.requested_cpu_slots == 12 <= derived.cpu_budget == 15
    with pytest.raises(ValueError, match="oversubscribe"):
        resource_config("laptop", cpu_count=8, model_threads=4, parallel_trials=2, process_concurrency=1)


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


def test_load_rejects_model_name_mismatch(tmp_path: Path):
    path = tmp_path / "models" / "wait_time" / "v1"
    path.mkdir(parents=True)
    (path / "meta.json").write_text(
        store.canonical_json({"model_name": "refusal_risk", "version": "v1", "model_files": []}), encoding="utf-8"
    )
    store.write_artifact_manifest(path)
    store.set_current(tmp_path, "wait_time", "v1")
    with pytest.raises(store.ArtifactIntegrityError, match="model name mismatch"):
        store.load(tmp_path, "wait_time")


def registration_fixture(tmp_path: Path) -> dict:
    run = ExperimentRun.start(tmp_path, run_plan(), run_id="registration")
    key, model_path, checksum = complete_artifact_checkpoint(run, tmp_path)
    run.complete([key])
    run.release_lock()
    return {
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
            "evaluation_status": "completed",
            "checkpoint_file": key.filename,
            "model_family": store.MODEL_CONTRACTS["wait_time"]["family"],
            "prediction_targets": store.MODEL_CONTRACTS["wait_time"]["prediction_targets"],
        },
    }


def test_registration_accepts_completed_consistent_run(tmp_path: Path):
    assert store.registration_evidence(registration_fixture(tmp_path))["lineage"] == "complete"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model_family", "wrong_family", "wrong model family"),
        ("prediction_targets", ["wrong_target"], "wrong prediction targets"),
    ],
)
def test_registration_rejects_family_or_target_mismatch(tmp_path: Path, field: str, value: object, message: str):
    loaded = registration_fixture(tmp_path)
    loaded["meta"][field] = value
    with pytest.raises(store.ArtifactIntegrityError, match=message):
        store.registration_evidence(loaded)


def test_evaluation_state_is_honest_and_required_for_run_completion(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, run_plan(), run_id="pending-evaluation")
    key, _, _ = complete_artifact_checkpoint(run, tmp_path, evaluated=False)
    checkpoint = run.reusable_checkpoint(key)
    assert checkpoint["status"] == "completed"
    assert checkpoint["evaluation"]["status"] == "pending"
    with pytest.raises(RuntimeError, match="unevaluated"):
        run.complete([key])
    run.release_lock()


def test_checkpoint_serialization_and_reuse_states(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, run_plan(), run_id="checkpoint-states")
    incomplete = CheckpointKey("wait_time", trial_id="incomplete", forecast_origin="2025-03-02")
    run.start_checkpoint(incomplete, parameters={"depth": 4})
    assert run.reusable_checkpoint(incomplete, parameters={"depth": 4}) is None

    failed = CheckpointKey("wait_time", trial_id="failed")
    run.start_checkpoint(failed)
    run.fail_checkpoint(failed, RuntimeError("training stopped"), tmp_path)
    assert run.reusable_checkpoint(failed) is None

    complete = CheckpointKey("wait_time", trial_id="complete", fold_id="fold-a")
    run.start_checkpoint(complete, parameters={"depth": 6})
    run.complete_checkpoint(
        complete,
        parameters={"depth": 6},
        metrics={"mae": 1.0},
        evaluation_status="completed",
    )
    checkpoint_path = run.checkpoint_path(complete)
    parsed = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert checkpoint_path.read_text(encoding="utf-8") == store.canonical_json(parsed)
    assert run.reusable_checkpoint(complete, parameters={"depth": 6}) == parsed
    with pytest.raises(CheckpointIncompatibleError, match="incompatible scientific identity"):
        run.reusable_checkpoint(complete, parameters={"depth": 7})
    with pytest.raises(RuntimeError, match="immutable"):
        run.start_checkpoint(complete, parameters={"depth": 6})
    run.release_lock()


def test_run_lock_mutual_exclusion_and_normal_release(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, run_plan(), run_id="locked")
    with pytest.raises(RunLockedError, match="explicitly recover"):
        ExperimentRun.start(tmp_path, run_plan(), resume_run_id="locked")
    run.release_lock()
    resumed = ExperimentRun.start(tmp_path, run_plan(), resume_run_id="locked")
    resumed.release_lock()


def test_stale_lock_has_diagnostic_and_requires_explicit_recovery(tmp_path: Path):
    run_path = tmp_path / "runs" / "stale"
    lock = RunLock.acquire(run_path)
    diagnostic = RunLock.read(run_path)
    assert diagnostic["pid"] > 0
    with pytest.raises(RunLockedError, match="explicitly recover"):
        RunLock.acquire(run_path)
    assert RunLock.recover(run_path) == diagnostic
    lock.held = False
    replacement = RunLock.acquire(run_path)
    replacement.release()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"train_end": dt.date(2025, 3, 1)}, "training must end"),
        ({"backtest_origins": (dt.date(2025, 4, 1),)}, "inside the test period"),
        ({"prediction_horizon_days": 30}, "extends past the test period"),
        ({"forecast_origin": dt.date(2025, 4, 1)}, "must not exceed"),
        ({"origin_semantics": "first_forecast_day"}, "origin_semantics"),
    ],
)
def test_temporal_protocol_rejects_invalid_or_future_origins(changes: dict, message: str):
    with pytest.raises(ValueError, match=message):
        dataclasses.replace(temporal_protocol(), **changes).validate()


def test_temporal_protocol_accepts_last_observed_origin_semantics():
    protocol = temporal_protocol()
    protocol.validate()
    assert protocol.origin_semantics == "last_observed_day"
    assert protocol.backtest_origins[0] + dt.timedelta(days=1) == dt.date(2025, 3, 3)


def test_persisted_metadata_has_no_absolute_path_or_secret(tmp_path: Path):
    run = ExperimentRun.start(tmp_path, run_plan(), run_id="safe-metadata")
    persisted = run.manifest_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in persisted
    assert json.loads(persisted)["run_id"] == "safe-metadata"
    with pytest.raises(ValueError, match="absolute local path"):
        assert_safe_metadata({"artifact": "/tmp/private/model.txt"})
    with pytest.raises(ValueError, match="sensitive field"):
        assert_safe_metadata({"api_token": "do-not-persist"})
    run.release_lock()
