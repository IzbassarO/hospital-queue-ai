"""Reproducible experiment identity, resource policy, manifests, and resumable model checkpoints."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
from dataclasses import asdict
from pathlib import Path

import yaml

from hqai_ml.registry import store
from hqai_ml.registry.resources import ResourceConfig

RUN_SCHEMA_VERSION = 1
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SENSITIVE_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|credential)", re.I)
WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
LIBRARIES = ("python", "numpy", "pandas", "pyarrow", "duckdb", "lightgbm", "scikit-learn", "shap")
PREDICTION_TARGETS = {
    "wait_time": ["wait_days"],
    "refusal_risk": ["outcome_refused"],
    "load_forecast": ["registrations", "hospitalizations"],
}
MODEL_FAMILIES = {
    "wait_time": "gradient_boosted_regression",
    "refusal_risk": "gradient_boosted_binary_classification",
    "load_forecast": "global_gradient_boosted_count_forecast",
}
MUTABLE_RUN_FIELDS = {
    "artifacts",
    "baseline_metrics",
    "checkpoints",
    "ended_at",
    "evaluation",
    "failure",
    "metrics",
    "status",
}


class CheckpointIncompatibleError(RuntimeError):
    """A requested checkpoint belongs to different code, data, configuration, or resources."""


def _hash_object(obj: object) -> str:
    return hashlib.sha256(store.canonical_json(obj).encode()).hexdigest()


def yaml_identity(paths: list[Path], root: Path) -> dict:
    documents = {
        path.relative_to(root).as_posix(): yaml.safe_load(path.read_text(encoding="utf-8")) for path in sorted(paths)
    }
    return {"sha256": _hash_object(documents), "files": sorted(documents)}


def source_identity(root: Path) -> dict:
    paths = sorted(
        [path for directory in (root / "ml/hqai_ml", root / "ml/pipelines") for path in directory.rglob("*.py")]
        + [root / "ml/pyproject.toml"]
    )
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return {"sha256": digest.hexdigest(), "files": [path.relative_to(root).as_posix() for path in paths]}


def dataset_identity(processed_dir: Path, root: Path) -> dict:
    manifest_path = processed_dir / "_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"{manifest_path} missing — run `make ingest` first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    semantic = {
        key: manifest[key]
        for key in ("params", "sources", "tables", "dim_region", "dim_organization", "dim_icd")
        if key in manifest
    }
    parquet = []
    for name in sorted(manifest.get("tables", {})):
        path = processed_dir / f"{name}.parquet"
        if not path.is_file():
            raise FileNotFoundError(f"{path} missing — rerun `make ingest`")
        parquet.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "rows": manifest["tables"][name]["rows"],
                "sha256": store.sha256_file(path),
            }
        )
    payload = {"semantic_manifest": semantic, "processed_files": parquet}
    return {
        "identity_sha256": _hash_object(payload),
        "input_manifest": manifest_path.relative_to(root).as_posix(),
        "input_manifest_sha256": store.sha256_file(manifest_path),
        "processed_files": parquet,
    }


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def code_identity(root: Path) -> dict:
    return {
        "git_commit": _git(root, "rev-parse", "HEAD"),
        "dirty_worktree": bool(_git(root, "status", "--short")),
        "source": source_identity(root),
    }


def library_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in LIBRARIES[1:]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _walk_metadata(value: object, key: str = ""):
    if isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk_metadata(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _walk_metadata(child, key)
    else:
        yield key, value


def assert_safe_metadata(metadata: dict) -> None:
    for key, value in _walk_metadata(metadata):
        if SENSITIVE_KEY.search(key) and value not in (None, "", [], {}):
            raise ValueError(f"sensitive field {key!r} must not be persisted in experiment metadata")
        if isinstance(value, str) and (Path(value).is_absolute() or WINDOWS_PATH.match(value)):
            raise ValueError(f"absolute local path must not be persisted: {value!r}")


def safe_failure_message(exc: BaseException, root: Path) -> str:
    message = str(exc).replace(str(root.resolve()), ".")
    words = []
    for word in message.split():
        stripped = word.strip("'\"()[]{}.,:;")
        if Path(stripped).is_absolute() or WINDOWS_PATH.match(stripped):
            word = word.replace(stripped, "<local-path>")
        words.append(word)
    return " ".join(words)[:2000]


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def build_plan(
    *,
    root: Path,
    processed_dir: Path,
    configs_dir: Path,
    selected_models: list[str],
    resources: ResourceConfig,
    temporal_protocols: dict,
    hyperparameters: dict,
) -> dict:
    dataset = dataset_identity(processed_dir, root)
    config = yaml_identity(
        [configs_dir / "models.yaml", configs_dir / "ingest.yaml", configs_dir / "explain_templates.yaml"], root
    )
    code = code_identity(root)
    seed = int(hyperparameters["lightgbm"]["seed"])
    identity = {
        "models": selected_models,
        "dataset_identity": dataset["identity_sha256"],
        "config_identity": config["sha256"],
        "code_identity": code["source"]["sha256"],
        "git_commit": code["git_commit"],
        "resources": asdict(resources),
        "temporal_protocols": temporal_protocols,
        "hyperparameters": hyperparameters,
    }
    return {
        "identity_sha256": _hash_object(identity),
        "models": selected_models,
        "model_families": {name: MODEL_FAMILIES[name] for name in selected_models},
        "prediction_targets": {name: PREDICTION_TARGETS[name] for name in selected_models},
        "dataset": dataset,
        "configuration": config,
        "code": code,
        "temporal_protocols": temporal_protocols,
        "random_seeds": {
            "python": seed,
            "numpy": seed,
            "model": seed,
            "lightgbm": {
                key: hyperparameters["lightgbm"].get(key)
                for key in ("seed", "bagging_seed", "feature_fraction_seed", "data_random_seed")
                if hyperparameters["lightgbm"].get(key) is not None
            },
        },
        "hyperparameters": hyperparameters,
        "implementation_versions": library_versions(),
        "platform": {"system": platform.system(), "machine": platform.machine()},
        "resources": asdict(resources),
    }


class ExperimentRun:
    """Atomic run manifest. Identity fields freeze at creation; completed runs are immutable."""

    def __init__(self, artifacts_dir: Path, manifest: dict):
        self.artifacts_dir = artifacts_dir
        self.manifest = manifest
        self.path = artifacts_dir / "runs" / manifest["run_id"]
        self.manifest_path = self.path / "run.json"

    @classmethod
    def start(
        cls,
        artifacts_dir: Path,
        plan: dict,
        *,
        run_id: str | None = None,
        resume_run_id: str | None = None,
    ) -> ExperimentRun:
        if run_id and resume_run_id:
            raise ValueError("--run-id and --resume are mutually exclusive")
        if resume_run_id:
            path = artifacts_dir / "runs" / resume_run_id / "run.json"
            if not path.is_file():
                raise FileNotFoundError(f"run {resume_run_id!r} does not exist")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest["identity_sha256"] != plan["identity_sha256"]:
                raise CheckpointIncompatibleError(
                    "resume rejected: code, data, configuration, temporal protocol, models, or resources changed"
                )
            run = cls(artifacts_dir, manifest)
            if manifest["status"] != "completed":
                run._update(status="running", ended_at=None, evaluation={"status": "pending"}, failure=None)
            return run
        if run_id is None:
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"{stamp}-{plan['identity_sha256'][:12]}"
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must contain only letters, digits, dot, underscore, and hyphen")
        manifest = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": utc_now(),
            "ended_at": None,
            **plan,
            "checkpoints": {},
            "metrics": {},
            "baseline_metrics": {},
            "artifacts": {},
            "evaluation": {"status": "pending"},
            "failure": None,
            "mutable_while_running": sorted(MUTABLE_RUN_FIELDS),
        }
        assert_safe_metadata(manifest)
        run = cls(artifacts_dir, manifest)
        if run.path.exists():
            raise FileExistsError(f"run {run_id!r} already exists; use --resume {run_id}")
        run.path.mkdir(parents=True)
        run._write()
        return run

    def _write(self) -> None:
        assert_safe_metadata(self.manifest)
        store.atomic_write_text(self.manifest_path, store.canonical_json(self.manifest))

    def _update(self, **changes) -> None:
        if self.manifest["status"] == "completed":
            raise RuntimeError("completed run manifests are immutable")
        unexpected = changes.keys() - MUTABLE_RUN_FIELDS
        if unexpected:
            raise ValueError(f"attempted to mutate immutable run fields: {sorted(unexpected)}")
        self.manifest.update(changes)
        self._write()

    def checkpoint_identity(self, model_name: str) -> str:
        return _hash_object({"run_identity": self.manifest["identity_sha256"], "model": model_name})

    def reusable_checkpoint(self, model_name: str) -> dict | None:
        checkpoint = self.manifest["checkpoints"].get(model_name)
        if not checkpoint or checkpoint.get("status") != "completed":
            return None
        if checkpoint.get("identity_sha256") != self.checkpoint_identity(model_name):
            raise CheckpointIncompatibleError(f"checkpoint {model_name!r} has an incompatible identity")
        artifact = checkpoint["artifact"]
        path = (self.artifacts_dir / artifact["path"]).resolve()
        if not path.is_relative_to(self.artifacts_dir.resolve()):
            raise CheckpointIncompatibleError(f"checkpoint {model_name!r} has an invalid artifact path")
        verified = store.verify_artifact_manifest(path, adopt_legacy=False)
        if verified["content_sha256"] != artifact["sha256"]:
            raise store.ArtifactIntegrityError(f"checkpoint {model_name!r} artifact identity changed")
        return checkpoint

    def start_checkpoint(self, model_name: str) -> None:
        checkpoints = dict(self.manifest["checkpoints"])
        checkpoints[model_name] = {
            "status": "running",
            "identity_sha256": self.checkpoint_identity(model_name),
            "started_at": utc_now(),
            "ended_at": None,
        }
        self._update(checkpoints=checkpoints)

    def complete_checkpoint(
        self,
        model_name: str,
        *,
        artifact_path: Path,
        artifact_sha256: str,
        version: str,
        metrics: dict,
        baseline_metrics: dict,
    ) -> None:
        current = self.manifest["checkpoints"].get(model_name)
        if not current or current.get("status") != "running":
            raise RuntimeError(f"checkpoint {model_name!r} was not started")
        verified = store.verify_artifact_manifest(artifact_path, adopt_legacy=False)
        if verified["content_sha256"] != artifact_sha256:
            raise store.ArtifactIntegrityError(f"checkpoint {model_name!r} artifact checksum does not match")
        relative = artifact_path.relative_to(self.artifacts_dir).as_posix()
        checkpoint = {
            "status": "completed",
            "identity_sha256": self.checkpoint_identity(model_name),
            "started_at": current["started_at"],
            "ended_at": utc_now(),
            "artifact": {"path": relative, "version": version, "sha256": artifact_sha256},
            "evaluation_status": "passed",
        }
        checkpoints = {**self.manifest["checkpoints"], model_name: checkpoint}
        self._update(
            checkpoints=checkpoints,
            metrics={**self.manifest["metrics"], model_name: metrics},
            baseline_metrics={**self.manifest["baseline_metrics"], model_name: baseline_metrics},
            artifacts={**self.manifest["artifacts"], model_name: checkpoint["artifact"]},
        )

    def complete(self) -> None:
        missing = [name for name in self.manifest["models"] if not self.reusable_checkpoint(name)]
        if missing:
            raise RuntimeError(f"cannot complete run; checkpoints incomplete: {missing}")
        self._update(status="completed", ended_at=utc_now(), evaluation={"status": "passed"}, failure=None)

    def fail(self, exc: BaseException, root: Path) -> None:
        if self.manifest["status"] == "completed":
            return
        self._update(
            status="failed",
            ended_at=utc_now(),
            evaluation={"status": "failed"},
            failure={"type": type(exc).__name__, "message": safe_failure_message(exc, root)},
        )
