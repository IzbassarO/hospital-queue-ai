"""Scientific experiment identity, execution records, locks, and atomic unit checkpoints."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import socket
import subprocess
import warnings
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

import yaml

from hqai_ml.registry import store
from hqai_ml.registry.resources import ResourceConfig

RUN_SCHEMA_VERSION = 2
CHECKPOINT_SCHEMA_VERSION = 1
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
KEY_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SENSITIVE_KEY = re.compile(r"(?:password|passwd|secret|token|api[_-]?key|credential)", re.I)
WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
SCIENTIFIC_LIBRARIES = ("python", "lightgbm", "numpy", "pandas", "scikit-learn", "duckdb", "shap")
EXECUTION_HYPERPARAMETERS = {"num_threads", "num_thread", "n_jobs"}
MUTABLE_RUN_FIELDS = {
    "artifacts",
    "baseline_metrics",
    "checkpoint_summary",
    "ended_at",
    "evaluation",
    "executions",
    "failure",
    "metrics",
    "status",
}


class CheckpointIncompatibleError(RuntimeError):
    """A checkpoint or run belongs to different scientific inputs."""


class RunLockedError(RuntimeError):
    """Another writer owns the run directory lock."""


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


def implementation_versions() -> dict[str, str]:
    versions = {"python": platform.python_version()}
    for package in SCIENTIFIC_LIBRARIES[1:]:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def scientific_hyperparameters(hyperparameters: dict) -> dict:
    normalized = json.loads(store.canonical_json(hyperparameters))
    lightgbm = normalized.get("lightgbm", {})
    normalized["lightgbm"] = {key: value for key, value in lightgbm.items() if key not in EXECUTION_HYPERPARAMETERS}
    return normalized


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


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_start_identity(pid: int) -> str | None:
    """Best-effort local PID-reuse fence using procfs or the standard local ``ps`` command."""
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        # Field 22 is the process start time in clock ticks. The command name may contain spaces.
        fields_after_command = proc_stat.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
        return f"procfs:{fields_after_command[19]}"
    except (IndexError, OSError):
        pass
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    started = result.stdout.strip()
    return f"ps:{started}" if result.returncode == 0 and started else None


def execution_metadata(resources: ResourceConfig) -> dict:
    return {
        "resources": asdict(resources),
        "platform": {"system": platform.system(), "machine": platform.machine()},
    }


def build_plan(
    *,
    root: Path,
    processed_dir: Path,
    configs_dir: Path,
    selected_models: list[str],
    resources: ResourceConfig,
    temporal_protocols: dict,
    hyperparameters: dict,
    versions: dict[str, str] | None = None,
) -> dict:
    dataset = dataset_identity(processed_dir, root)
    configuration = yaml_identity(
        [configs_dir / "models.yaml", configs_dir / "ingest.yaml", configs_dir / "explain_templates.yaml"], root
    )
    code = code_identity(root)
    normalized_hyperparameters = scientific_hyperparameters(hyperparameters)
    versions = versions or implementation_versions()
    seed = int(normalized_hyperparameters["lightgbm"]["seed"])
    seeds = {
        "python": seed,
        "numpy": seed,
        "model": seed,
        "lightgbm": {
            key: normalized_hyperparameters["lightgbm"].get(key)
            for key in ("seed", "bagging_seed", "feature_fraction_seed", "data_random_seed")
            if normalized_hyperparameters["lightgbm"].get(key) is not None
        },
    }
    models = sorted(selected_models)
    families = {name: store.MODEL_CONTRACTS[name]["family"] for name in models}
    targets = {name: store.MODEL_CONTRACTS[name]["prediction_targets"] for name in models}
    scientific = {
        "models": models,
        "candidates": dict.fromkeys(models, "current"),
        "model_families": families,
        "prediction_targets": targets,
        "dataset_identity": dataset["identity_sha256"],
        "config_identity": configuration["sha256"],
        "code_identity": code["source"]["sha256"],
        "implementation_versions": versions,
        "temporal_protocols": temporal_protocols,
        "hyperparameters": normalized_hyperparameters,
        "random_seeds": seeds,
    }
    identity = _hash_object(scientific)
    return {
        "scientific_identity_sha256": identity,
        "identity_sha256": identity,
        "scientific_identity": scientific,
        "models": models,
        "model_families": families,
        "prediction_targets": targets,
        "dataset": dataset,
        "configuration": configuration,
        "code": code,
        "temporal_protocols": temporal_protocols,
        "random_seeds": seeds,
        "hyperparameters": normalized_hyperparameters,
        "implementation_versions": versions,
        "execution": execution_metadata(resources),
    }


@dataclass(frozen=True)
class CheckpointKey:
    model_name: str
    candidate_id: str = "current"
    trial_id: str = "default"
    fold_id: str | None = None
    forecast_origin: str | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("model_name", self.model_name),
            ("candidate_id", self.candidate_id),
            ("trial_id", self.trial_id),
            ("fold_id", self.fold_id),
        ):
            if value is not None and not KEY_PART.fullmatch(value):
                raise ValueError(f"invalid checkpoint {name}: {value!r}")
        if self.forecast_origin is not None:
            try:
                dt.date.fromisoformat(self.forecast_origin)
            except ValueError as exc:
                raise ValueError("forecast_origin must be an ISO date using last-observed-day semantics") from exc

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def identifier(self) -> str:
        return _hash_object(self.to_dict())

    @property
    def filename(self) -> str:
        return f"{self.model_name}--{self.candidate_id}--{self.trial_id}--{self.identifier[:16]}.json"

    @classmethod
    def model(cls, model_name: str) -> CheckpointKey:
        return cls(model_name=model_name)


class RunLock:
    """One local writer per run. Stale locks require explicit recovery."""

    FILENAME = ".run.lock"

    def __init__(self, path: Path, metadata: dict):
        self.path = path
        self.metadata = metadata
        self.held = True

    @classmethod
    def acquire(cls, run_path: Path) -> RunLock:
        run_path.mkdir(parents=True, exist_ok=True)
        path = run_path / cls.FILENAME
        metadata = {
            "lock_id": uuid4().hex,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "process_start": _process_start_identity(os.getpid()),
            "acquired_at": utc_now(),
        }
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            diagnostic = cls.read(run_path)
            raise RunLockedError(
                f"run is locked by {diagnostic}; if the writer was hard-killed, explicitly recover the stale lock"
            ) from exc
        try:
            os.write(descriptor, store.canonical_json(metadata).encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return cls(path, metadata)

    @classmethod
    def read(cls, run_path: Path) -> dict:
        path = run_path / cls.FILENAME
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return {"diagnostic": f"unreadable lock: {exc}"}

    @classmethod
    def recover(
        cls,
        run_path: Path,
        *,
        confirm_lock_id: str,
        force_remote: bool = False,
    ) -> dict:
        """Remove a confirmed stale lock; never infer that a remote-host lock is stale."""
        path = run_path / cls.FILENAME
        if not path.exists():
            raise FileNotFoundError(f"no stale lock exists for {run_path.name!r}")
        diagnostic = cls.read(run_path)
        recorded_id = diagnostic.get("lock_id")
        if not recorded_id or confirm_lock_id != recorded_id:
            raise RunLockedError("lock-id confirmation does not match the current on-disk lock")
        recorded_host = diagnostic.get("hostname")
        current_host = socket.gethostname()
        if recorded_host != current_host:
            if not force_remote:
                raise RunLockedError(
                    "lock belongs to another or unknown host; refuse ambiguous recovery unless "
                    "--force-remote-lock-recovery is explicitly supplied"
                )
        else:
            try:
                pid = int(diagnostic["pid"])
            except (KeyError, TypeError, ValueError) as exc:
                raise RunLockedError("local lock has no usable PID; refusing ambiguous recovery") from exc
            if _pid_alive(pid):
                recorded_start = diagnostic.get("process_start")
                current_start = _process_start_identity(pid)
                if not recorded_start or not current_start or recorded_start == current_start:
                    raise RunLockedError("refusing recovery: the recorded local lock owner is still alive")
                # A different start identity means the PID was reused after the original owner exited.
        current = cls.read(run_path)
        if current.get("lock_id") != confirm_lock_id:
            raise RunLockedError("lock ownership changed during recovery; refusing to remove the replacement")
        path.unlink()
        recovery = {
            "recovered_lock": diagnostic,
            "recovered_at": utc_now(),
            "recovered_by": {"hostname": current_host, "pid": os.getpid()},
            "forced_remote": force_remote,
        }
        audit_path = run_path / f"lock-recovery-{uuid4().hex}.json"
        store.atomic_write_text(audit_path, store.canonical_json(recovery))
        return recovery

    def assert_owned(self) -> None:
        """Fence a writer by comparing its token with the lock currently present on disk."""
        if not self.held:
            raise RunLockedError("run writer lock is not held")
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.held = False
            raise RunLockedError("run lock disappeared or became unreadable; writer is fenced") from exc
        if current.get("lock_id") != self.metadata["lock_id"]:
            self.held = False
            raise RunLockedError("run lock ownership changed; writer is fenced")

    def release(self) -> None:
        if not self.held:
            return
        self.assert_owned()
        self.path.unlink()
        self.held = False


class ExperimentRun:
    """Locked atomic run manifest with independently stored immutable completed checkpoints."""

    def __init__(self, artifacts_dir: Path, manifest: dict, lock: RunLock | None):
        self.artifacts_dir = artifacts_dir
        self.manifest = manifest
        self.path = artifacts_dir / "runs" / manifest["run_id"]
        self.manifest_path = self.path / "run.json"
        self.checkpoints_path = self.path / "checkpoints"
        self.lock = lock

    @classmethod
    def read_only(cls, artifacts_dir: Path, run_id: str) -> ExperimentRun:
        """Open a run for checkpoint inspection without acquiring writer authority."""
        manifest_path = artifacts_dir / "runs" / run_id / "run.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"run {run_id!r} does not exist")
        return cls(artifacts_dir, json.loads(manifest_path.read_text(encoding="utf-8")), None)

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
            run_path = artifacts_dir / "runs" / resume_run_id
            manifest_path = run_path / "run.json"
            if not manifest_path.is_file():
                raise FileNotFoundError(f"run {resume_run_id!r} does not exist")
            lock = RunLock.acquire(run_path)
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                recorded = manifest["scientific_identity_sha256"]
                current = plan["scientific_identity_sha256"]
                if recorded != current:
                    if manifest.get("implementation_versions") != plan.get("implementation_versions"):
                        raise CheckpointIncompatibleError(
                            "resume rejected: scientifically relevant implementation versions changed"
                        )
                    raise CheckpointIncompatibleError(
                        "resume rejected: model, code, data, configuration, temporal protocol, hyperparameters, "
                        "or seeds changed"
                    )
                run = cls(artifacts_dir, manifest, lock)
                run._warn_on_platform_change(plan["execution"]["platform"])
                if manifest["status"] != "completed":
                    run._record_execution(plan["execution"])
                return run
            except BaseException:
                lock.release()
                raise
        if run_id is None:
            stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
            run_id = f"{stamp}-{plan['scientific_identity_sha256'][:12]}"
        if not RUN_ID.fullmatch(run_id):
            raise ValueError("run_id must contain only letters, digits, dot, underscore, and hyphen")
        run_path = artifacts_dir / "runs" / run_id
        if run_path.exists():
            raise FileExistsError(f"run {run_id!r} already exists; use --resume {run_id}")
        run_path.mkdir(parents=True)
        lock = RunLock.acquire(run_path)
        manifest = {
            "schema_version": RUN_SCHEMA_VERSION,
            "run_id": run_id,
            "status": "running",
            "started_at": utc_now(),
            "ended_at": None,
            **{key: value for key, value in plan.items() if key != "execution"},
            "executions": [],
            "checkpoint_summary": {},
            "metrics": {},
            "baseline_metrics": {},
            "artifacts": {},
            "evaluation": {"status": "pending"},
            "failure": None,
            "mutable_while_running": sorted(MUTABLE_RUN_FIELDS),
        }
        assert_safe_metadata(manifest)
        run = cls(artifacts_dir, manifest, lock)
        try:
            run.checkpoints_path.mkdir()
            run._record_execution(plan["execution"], initial=True)
            return run
        except BaseException:
            lock.release()
            raise

    @property
    def current_execution(self) -> dict:
        return self.manifest["executions"][-1]

    def _warn_on_platform_change(self, current: dict) -> None:
        previous = {store.canonical_json(item["platform"]) for item in self.manifest.get("executions", [])}
        if previous and store.canonical_json(current) not in previous:
            warnings.warn(
                "resuming on a different platform/architecture; scientific identity matches but numerical "
                "bit-equivalence is not guaranteed",
                stacklevel=2,
            )

    def _record_execution(self, execution: dict, *, initial: bool = False) -> None:
        record = {
            "execution_id": uuid4().hex,
            "status": "running",
            "started_at": utc_now(),
            "ended_at": None,
            **execution,
        }
        executions = [*self.manifest["executions"], record]
        if initial:
            self.manifest["executions"] = executions
            self._write()
        else:
            self._update(
                executions=executions,
                status="running",
                ended_at=None,
                evaluation={"status": "pending"},
                failure=None,
            )

    def _write(self) -> None:
        self._require_lock()
        assert_safe_metadata(self.manifest)
        store.atomic_write_text(self.manifest_path, store.canonical_json(self.manifest))

    def _update(self, **changes) -> None:
        self._require_lock()
        if self.manifest["status"] == "completed":
            raise RuntimeError("completed run manifests are immutable")
        unexpected = changes.keys() - MUTABLE_RUN_FIELDS
        if unexpected:
            raise ValueError(f"attempted to mutate immutable run fields: {sorted(unexpected)}")
        self.manifest.update(changes)
        self._write()

    def _require_lock(self) -> None:
        if self.lock is None:
            raise RunLockedError("run writer lock is not held")
        self.lock.assert_owned()

    def _write_checkpoint(self, key: CheckpointKey, checkpoint: dict) -> None:
        self._require_lock()
        store.atomic_write_text(self.checkpoint_path(key), store.canonical_json(checkpoint))

    def checkpoint_path(self, key: CheckpointKey) -> Path:
        return self.checkpoints_path / key.filename

    def checkpoint_identity(self, key: CheckpointKey, parameters: dict | None = None) -> str:
        return _hash_object(
            {
                "run_scientific_identity": self.manifest["scientific_identity_sha256"],
                "key": key.to_dict(),
                "parameters": parameters or {},
            }
        )

    def _read_checkpoint(self, key: CheckpointKey) -> dict | None:
        path = self.checkpoint_path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def reusable_checkpoint(self, key: CheckpointKey, *, parameters: dict | None = None) -> dict | None:
        checkpoint = self._read_checkpoint(key)
        if checkpoint is None:
            return None
        expected = self.checkpoint_identity(key, parameters)
        if checkpoint.get("scientific_identity_sha256") != expected:
            raise CheckpointIncompatibleError(f"checkpoint {key.to_dict()!r} has an incompatible scientific identity")
        if checkpoint.get("status") != "completed":
            return None
        artifact = checkpoint.get("artifact")
        if artifact:
            path = (self.artifacts_dir / artifact["path"]).resolve()
            if not path.is_relative_to(self.artifacts_dir.resolve()):
                raise CheckpointIncompatibleError(f"checkpoint {key.to_dict()!r} has an invalid artifact path")
            verified = store.verify_artifact_manifest(path, adopt_legacy=False)
            if verified["content_sha256"] != artifact["sha256"]:
                raise store.ArtifactIntegrityError(f"checkpoint {key.to_dict()!r} artifact identity changed")
        return checkpoint

    def start_checkpoint(self, key: CheckpointKey, *, parameters: dict | None = None) -> dict:
        self._require_lock()
        if key.model_name not in self.manifest["models"]:
            raise ValueError(f"checkpoint model {key.model_name!r} is not part of this run")
        parameters = parameters or {}
        identity = self.checkpoint_identity(key, parameters)
        existing = self._read_checkpoint(key)
        if existing and existing.get("scientific_identity_sha256") != identity:
            raise CheckpointIncompatibleError(f"checkpoint {key.to_dict()!r} exists for incompatible inputs")
        if existing and existing.get("status") == "completed":
            raise RuntimeError(f"completed checkpoint {key.to_dict()!r} is immutable")
        checkpoint = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "key": key.to_dict(),
            "key_id": key.identifier,
            "status": "running",
            "scientific_identity_sha256": identity,
            "started_at": utc_now(),
            "ended_at": None,
            "parameters": parameters,
            "execution_id": self.current_execution["execution_id"],
            "execution": {
                "resources": self.current_execution["resources"],
                "platform": self.current_execution["platform"],
            },
            "evaluation": {"status": "pending"},
            "metrics": None,
            "baseline_metrics": None,
            "artifact": None,
            "failure": None,
        }
        assert_safe_metadata(checkpoint)
        self._write_checkpoint(key, checkpoint)
        self._refresh_checkpoint_summary()
        return checkpoint

    def complete_checkpoint(
        self,
        key: CheckpointKey,
        *,
        parameters: dict | None = None,
        metrics: dict | None = None,
        baseline_metrics: dict | None = None,
        evaluation_status: str = "pending",
        artifact_path: Path | None = None,
        artifact_sha256: str | None = None,
        version: str | None = None,
    ) -> dict:
        self._require_lock()
        if evaluation_status not in {"pending", "completed"}:
            raise ValueError("evaluation_status must be pending or completed")
        current = self._read_checkpoint(key)
        if not current or current.get("status") != "running":
            raise RuntimeError(f"checkpoint {key.to_dict()!r} was not started or is already immutable")
        expected = self.checkpoint_identity(key, parameters)
        if current["scientific_identity_sha256"] != expected:
            raise CheckpointIncompatibleError(f"checkpoint {key.to_dict()!r} changed scientific inputs")
        artifact = None
        supplied = (artifact_path, artifact_sha256, version)
        if any(value is not None for value in supplied):
            if not all(value is not None for value in supplied):
                raise ValueError("artifact path, SHA256, and version must be supplied together")
            assert artifact_path is not None and artifact_sha256 is not None and version is not None
            verified = store.verify_artifact_manifest(artifact_path, adopt_legacy=False)
            if verified["content_sha256"] != artifact_sha256:
                raise store.ArtifactIntegrityError(f"checkpoint {key.to_dict()!r} artifact checksum does not match")
            relative = artifact_path.relative_to(self.artifacts_dir).as_posix()
            artifact = {"path": relative, "version": version, "sha256": artifact_sha256}
        checkpoint = {
            **current,
            "status": "completed",
            "ended_at": utc_now(),
            "evaluation": {"status": evaluation_status},
            "metrics": metrics,
            "baseline_metrics": baseline_metrics,
            "artifact": artifact,
            "failure": None,
        }
        assert_safe_metadata(checkpoint)
        self._write_checkpoint(key, checkpoint)
        self._refresh_checkpoint_summary()
        if key == CheckpointKey.model(key.model_name):
            changes = {}
            if metrics is not None:
                changes["metrics"] = {**self.manifest["metrics"], key.model_name: metrics}
            if baseline_metrics is not None:
                changes["baseline_metrics"] = {
                    **self.manifest["baseline_metrics"],
                    key.model_name: baseline_metrics,
                }
            if artifact is not None:
                changes["artifacts"] = {**self.manifest["artifacts"], key.model_name: artifact}
            if changes:
                self._update(**changes)
        return checkpoint

    def fail_checkpoint(self, key: CheckpointKey, exc: BaseException, root: Path) -> None:
        self._require_lock()
        current = self._read_checkpoint(key)
        if not current or current.get("status") == "completed":
            raise RuntimeError(f"checkpoint {key.to_dict()!r} cannot transition to failed")
        failed = {
            **current,
            "status": "failed",
            "ended_at": utc_now(),
            "failure": {"type": type(exc).__name__, "message": safe_failure_message(exc, root)},
        }
        self._write_checkpoint(key, failed)
        self._refresh_checkpoint_summary()

    def interrupt_checkpoint(self, key: CheckpointKey) -> None:
        self._require_lock()
        current = self._read_checkpoint(key)
        if not current or current.get("status") == "completed":
            raise RuntimeError(f"checkpoint {key.to_dict()!r} cannot transition to interrupted")
        interrupted = {
            **current,
            "status": "interrupted",
            "ended_at": utc_now(),
            "failure": None,
        }
        self._write_checkpoint(key, interrupted)
        self._refresh_checkpoint_summary()

    def _refresh_checkpoint_summary(self) -> None:
        counts: dict[str, int] = {}
        for path in self.checkpoints_path.glob("*.json"):
            status = json.loads(path.read_text(encoding="utf-8")).get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        self._update(checkpoint_summary={"total": sum(counts.values()), "by_status": counts})

    def complete(self, required: list[CheckpointKey] | None = None) -> None:
        required = required or [CheckpointKey.model(name) for name in self.manifest["models"]]
        incomplete = []
        for key in required:
            checkpoint = self.reusable_checkpoint(key)
            if checkpoint is None or checkpoint["evaluation"]["status"] != "completed":
                incomplete.append(key.to_dict())
        if incomplete:
            raise RuntimeError(f"cannot complete run; checkpoints incomplete or unevaluated: {incomplete}")
        executions = list(self.manifest["executions"])
        executions[-1] = {**executions[-1], "status": "completed", "ended_at": utc_now()}
        self._update(
            status="completed",
            ended_at=utc_now(),
            executions=executions,
            evaluation={"status": "completed"},
            failure=None,
        )

    def fail(self, exc: BaseException, root: Path) -> None:
        if self.manifest["status"] == "completed":
            return
        executions = list(self.manifest["executions"])
        executions[-1] = {**executions[-1], "status": "failed", "ended_at": utc_now()}
        self._update(
            status="failed",
            ended_at=utc_now(),
            executions=executions,
            evaluation={"status": "pending"},
            failure={"type": type(exc).__name__, "message": safe_failure_message(exc, root)},
        )

    def pause(self) -> None:
        if self.manifest["status"] == "completed":
            return
        executions = list(self.manifest["executions"])
        executions[-1] = {**executions[-1], "status": "interrupted", "ended_at": utc_now()}
        self._update(status="interrupted", executions=executions)

    def release_lock(self) -> None:
        if self.lock is not None:
            self.lock.release()
