"""Checksummed, atomic filesystem model-artifact registry."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import lightgbm as lgb
import yaml

MANIFEST = "manifest.json"
ARTIFACT_MANIFEST = "artifact-manifest.json"
CARDS_CONFIG = "model_cards.yaml"
MODEL_CONTRACTS = {
    "patient_journey": {
        "family": "survival_and_competing_risk_tournament",
        "prediction_targets": ["hospitalized_by_horizon", "refused_by_horizon", "unresolved_at_horizon"],
    },
    "wait_time": {
        "family": "gradient_boosted_regression",
        "prediction_targets": ["wait_days"],
    },
    "refusal_risk": {
        "family": "gradient_boosted_binary_classification",
        "prediction_targets": ["outcome_refused"],
    },
    "load_forecast": {
        "family": "global_gradient_boosted_count_forecast",
        "prediction_targets": ["registrations", "hospitalizations"],
    },
}


class ArtifactIntegrityError(RuntimeError):
    """A registered artifact is missing, incomplete, or no longer matches its recorded digest."""


def canonical_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_text(path: Path, text: str) -> None:
    """Write text completely before atomically replacing the destination."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _dump(path: Path, obj: object, *, atomic: bool = False) -> None:
    text = canonical_json(obj)
    if atomic:
        atomic_write_text(path, text)
    else:
        path.write_text(text, encoding="utf-8")


def load_cards(configs_dir: Path) -> dict:
    path = configs_dir / CARDS_CONFIG
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


def _root(artifacts_dir: Path) -> Path:
    return artifacts_dir / "models"


def read_manifest(artifacts_dir: Path) -> dict:
    path = _root(artifacts_dir) / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def artifact_files(path: Path) -> list[dict[str, str | int]]:
    return [
        {"path": file.relative_to(path).as_posix(), "bytes": file.stat().st_size, "sha256": sha256_file(file)}
        for file in sorted(path.rglob("*"))
        if file.is_file() and file.name != ARTIFACT_MANIFEST
    ]


def write_artifact_manifest(path: Path, *, adopted_legacy: bool = False) -> dict:
    files = artifact_files(path)
    content_sha256 = hashlib.sha256(canonical_json({"files": files}).encode()).hexdigest()
    manifest = {
        "schema_version": 1,
        "content_sha256": content_sha256,
        "adopted_legacy": adopted_legacy,
        "files": files,
    }
    _dump(path / ARTIFACT_MANIFEST, manifest, atomic=True)
    return manifest


def publish_artifact_directory(
    parent: Path,
    label: str,
    writer: Callable[[Path], None],
) -> tuple[Path, dict]:
    """Write a checksummed artifact in a unique partial directory, then atomically publish it.

    Unique attempt paths mean an abandoned partial directory or a crash after publication but before
    checkpoint completion cannot wedge a retry. Such orphaned directories are harmless and auditable.
    """
    valid_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
    if not label or any(character not in valid_characters for character in label):
        raise ValueError("artifact label contains unsupported characters")
    parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex[:12]
    temporary = parent / f".{label}.partial-{token}"
    published = parent / f"{label}-{token}"
    temporary.mkdir()
    try:
        writer(temporary)
        manifest = write_artifact_manifest(temporary)
        os.replace(temporary, published)
        _fsync_directory(parent)
        return published, manifest
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def verify_artifact_manifest(path: Path, *, adopt_legacy: bool = True) -> dict:
    manifest_path = path / ARTIFACT_MANIFEST
    if not manifest_path.exists():
        if not adopt_legacy:
            raise ArtifactIntegrityError(f"artifact manifest missing for {path.name!r}")
        write_artifact_manifest(path, adopted_legacy=True)
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError(f"cannot read artifact manifest for {path.name!r}: {exc}") from exc
    actual_files = artifact_files(path)
    actual_sha256 = hashlib.sha256(canonical_json({"files": actual_files}).encode()).hexdigest()
    if recorded.get("files") != actual_files or recorded.get("content_sha256") != actual_sha256:
        raise ArtifactIntegrityError(
            f"artifact checksum mismatch for {path.name!r}; the registered files were replaced or corrupted"
        )
    return recorded


def save(
    artifacts_dir: Path,
    model_name: str,
    boosters: dict[str, lgb.Booster],
    *,
    features: list[str],
    categories: dict,
    meta: dict,
    metrics: dict,
    extra: dict[str, object] | None = None,
    make_current: bool = False,
) -> tuple[str, Path]:
    """Atomically publish a new immutable version directory; return ``(version, path)``."""
    now = dt.datetime.now(dt.UTC)
    version = now.strftime("%Y%m%d-%H%M%S")
    base = _root(artifacts_dir) / model_name
    base.mkdir(parents=True, exist_ok=True)
    path, suffix = base / version, 2
    while path.exists():
        version = f"{now:%Y%m%d-%H%M%S}-{suffix}"
        path, suffix = base / version, suffix + 1
    temporary = base / f".{version}.partial-{os.getpid()}"
    temporary.mkdir()
    try:
        for filename, booster in boosters.items():
            booster.save_model(str(temporary / filename))
        _dump(temporary / "features.json", {"features": features, "categorical": list(categories)})
        _dump(temporary / "categories.json", categories)
        _dump(
            temporary / "meta.json",
            {
                **meta,
                "model_name": model_name,
                "version": version,
                "trained_at": now.isoformat(timespec="seconds"),
                "model_files": sorted(boosters),
            },
        )
        _dump(temporary / "metrics.json", metrics)
        for filename, obj in sorted((extra or {}).items()):
            _dump(temporary / filename, obj)
        write_artifact_manifest(temporary)
        os.replace(temporary, path)
        _fsync_directory(base)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    if make_current:
        set_current(artifacts_dir, model_name, version)
    return version, path


def set_current(artifacts_dir: Path, model_name: str, version: str) -> None:
    set_current_many(artifacts_dir, {model_name: version})


def set_current_many(artifacts_dir: Path, versions: dict[str, str]) -> None:
    """Validate every selected artifact, then publish the complete current-set update atomically."""
    if not versions:
        raise ValueError("at least one model version is required for current-set publication")
    validated = {}
    for model_name, version in sorted(versions.items()):
        path = version_dir(artifacts_dir, model_name, version)
        artifact = verify_artifact_manifest(path)
        meta = load_json(path, "meta.json")
        if meta.get("model_name") != model_name or meta.get("version") != version:
            raise ArtifactIntegrityError(
                f"artifact identity mismatch for current pointer {model_name!r} version {version!r}"
            )
        validated[model_name] = artifact
    manifest = read_manifest(artifacts_dir)
    updated_at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    for model_name, version in sorted(versions.items()):
        manifest[model_name] = {
            "current": version,
            "path": f"models/{model_name}/{version}",
            "artifact_sha256": validated[model_name]["content_sha256"],
            "updated_at": updated_at,
        }
    _dump(_root(artifacts_dir) / MANIFEST, manifest, atomic=True)


def version_dir(artifacts_dir: Path, model_name: str, version: str | None = None) -> Path:
    if version is None:
        manifest = read_manifest(artifacts_dir)
        if model_name not in manifest:
            raise FileNotFoundError(f"no current version of {model_name!r} — run `make train`")
        version = manifest[model_name]["current"]
    path = _root(artifacts_dir) / model_name / version
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def load_json(path: Path, name: str):
    return json.loads((path / name).read_text(encoding="utf-8"))


def load(artifacts_dir: Path, model_name: str, version: str | None = None) -> dict:
    """Load a model only after every registered file passes SHA256 verification."""
    current_entry = None
    if version is None:
        current_entry = read_manifest(artifacts_dir).get(model_name)
    path = version_dir(artifacts_dir, model_name, version)
    artifact_manifest = verify_artifact_manifest(path)
    expected_sha256 = current_entry.get("artifact_sha256") if current_entry else None
    if expected_sha256 and expected_sha256 != artifact_manifest["content_sha256"]:
        raise ArtifactIntegrityError(
            f"current pointer checksum mismatch for {model_name!r}; the version identity was replaced"
        )
    if current_entry is not None and not expected_sha256:
        set_current(artifacts_dir, model_name, current_entry["current"])
    meta = load_json(path, "meta.json")
    if meta.get("model_name") != model_name:
        raise ArtifactIntegrityError(
            f"artifact model name mismatch: requested {model_name!r}, metadata declares {meta.get('model_name')!r}"
        )
    out = {
        "path": path,
        "meta": meta,
        "version": meta["version"],
        "artifact_manifest": artifact_manifest,
        "artifact_sha256": artifact_manifest["content_sha256"],
        "boosters": {filename: lgb.Booster(model_file=str(path / filename)) for filename in meta["model_files"]},
        "features": load_json(path, "features.json")["features"],
        "categories": load_json(path, "categories.json"),
        "metrics": load_json(path, "metrics.json"),
    }
    for extra in path.glob("*.json"):
        if extra.name not in {ARTIFACT_MANIFEST, "meta.json", "features.json", "categories.json", "metrics.json"}:
            out[extra.stem] = load_json(path, extra.name)
    return out


def registration_evidence(artifact: dict) -> dict:
    """Return registration eligibility without pretending old artifacts have modern lineage."""
    meta, metrics = artifact["meta"], artifact["metrics"]
    verified = verify_artifact_manifest(
        artifact["path"], adopt_legacy=artifact["artifact_manifest"].get("adopted_legacy") is True
    )
    if verified["content_sha256"] != artifact["artifact_sha256"]:
        raise ArtifactIntegrityError(f"artifact {artifact['version']!r} checksum changed before registration")
    evaluated = bool(metrics) and bool(meta.get("training_window"))
    lineage_fields = (
        "run_id",
        "dataset_identity",
        "config_identity",
        "code_identity",
        "evaluation_status",
        "checkpoint_file",
    )
    has_lineage = any(meta.get(field) for field in lineage_fields)
    complete_lineage = (
        all(meta.get(field) for field in lineage_fields)
        and bool(meta.get("model_family"))
        and bool(meta.get("prediction_targets"))
    )
    adopted_legacy = artifact["artifact_manifest"].get("adopted_legacy") is True
    if not evaluated:
        raise ArtifactIntegrityError(f"artifact {artifact['version']!r} has no successful evaluation evidence")
    if has_lineage and not complete_lineage:
        raise ArtifactIntegrityError(f"artifact {artifact['version']!r} has incomplete lineage evidence")
    if complete_lineage and meta["evaluation_status"] != "completed":
        raise ArtifactIntegrityError(f"artifact {artifact['version']!r} has no completed evaluation")
    if not complete_lineage and not adopted_legacy:
        raise ArtifactIntegrityError(f"artifact {artifact['version']!r} has no attributable training run")
    if complete_lineage:
        contract = MODEL_CONTRACTS.get(meta["model_name"])
        if contract is None:
            raise ArtifactIntegrityError(f"artifact declares unknown model {meta['model_name']!r}")
        if meta["model_family"] != contract["family"]:
            raise ArtifactIntegrityError(f"artifact {artifact['version']!r} has the wrong model family")
        if meta["prediction_targets"] != contract["prediction_targets"]:
            raise ArtifactIntegrityError(f"artifact {artifact['version']!r} has the wrong prediction targets")
        run_path = artifact["path"].parents[2] / "runs" / meta["run_id"] / "run.json"
        checkpoint_path = run_path.parent / "checkpoints" / meta["checkpoint_file"]
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            consistent = (
                run["status"] == "completed"
                and run["evaluation"]["status"] == "completed"
                and run["dataset"]["identity_sha256"] == meta["dataset_identity"]
                and run["configuration"]["sha256"] == meta["config_identity"]
                and run["code"]["source"]["sha256"] == meta["code_identity"]
                and checkpoint["key"]["model_name"] == meta["model_name"]
                and checkpoint["status"] == "completed"
                and checkpoint["evaluation"]["status"] == "completed"
                and checkpoint["artifact"]["sha256"] == artifact["artifact_sha256"]
                and checkpoint["artifact"]["path"]
                == artifact["path"].relative_to(artifact["path"].parents[2]).as_posix()
                and run["model_families"][meta["model_name"]] == meta["model_family"]
                and run["prediction_targets"][meta["model_name"]] == meta["prediction_targets"]
            )
        except (KeyError, OSError, json.JSONDecodeError) as exc:
            raise ArtifactIntegrityError(
                f"artifact {artifact['version']!r} cannot be linked to a completed run manifest"
            ) from exc
        if not consistent:
            raise ArtifactIntegrityError(f"artifact {artifact['version']!r} conflicts with its run manifest")
    evidence = {
        "eligible": True,
        "lineage": "complete" if complete_lineage else "legacy_unattributed",
        "artifact_sha256": artifact["artifact_sha256"],
        "run_id": None,
        "dataset_identity": None,
        "config_identity": None,
        "code_identity": None,
        "evaluation_status": None,
    }
    if complete_lineage:
        evidence.update({field: meta[field] for field in lineage_fields if field != "checkpoint_file"})
    return evidence
