"""Release contract of models/: every shipped file matches models/manifest.json, the native files are byte-identical
to their checksummed artifacts, and each standalone predict.py (run as a subprocess and imported by path, never through
hqai_ml) and joblib bundle reproduce the predictions the repository's own code produced for the shipped example rows.
No database and no model fitting."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
MANIFEST = json.loads((MODELS / "manifest.json").read_text(encoding="utf-8"))
RELEASED = sorted(name for name in MANIFEST["models"] if (MODELS / name / "predict.py").exists())
KEY_COLUMNS = {"referral_id", "series_id", "target", "horizon", "registration_date", "origin_date", "target_date"}
COUNT_MODELS = {"load_forecast", "flow_quantile"}
MAX_FILE_BYTES = 50 * 1024 * 1024
ABSOLUTE_TOLERANCE = 1e-6
RELATIVE_TOLERANCE = 1e-6


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def shipped_files() -> dict[str, Path]:
    return {
        path.relative_to(MODELS).as_posix(): path
        for path in MODELS.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name != "manifest.json"
        and not path.name.startswith(".")
    }


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def assert_reproduced(name: str, actual: pd.DataFrame, expected: pd.DataFrame) -> None:
    """Every expected prediction column is reproduced; counts within 1e-6 relative, everything else within 1e-6."""
    assert len(actual) == len(expected)
    columns = [column for column in expected.columns if column not in KEY_COLUMNS]
    assert columns, "expected output has no prediction columns"
    for column in columns:
        assert column in actual.columns, f"{name}: missing output column {column!r}"
        got = actual[column].to_numpy(float)
        want = expected[column].to_numpy(float)
        if name in COUNT_MODELS:
            np.testing.assert_allclose(got, want, rtol=RELATIVE_TOLERANCE, atol=1e-9, err_msg=f"{name}.{column}")
        else:
            np.testing.assert_allclose(got, want, rtol=0, atol=ABSOLUTE_TOLERANCE, err_msg=f"{name}.{column}")


def load_standalone(name: str):
    """Import models/<name>/predict.py by path; the module must not depend on the repository packages."""
    path = MODELS / name / "predict.py"
    source = path.read_text(encoding="utf-8")
    assert "hqai_ml" not in source and "from pipelines" not in source, f"{name}/predict.py is not standalone"
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(f"released_{name}_predict", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_has_the_frozen_models():
    assert {"wait_time", "refusal_risk", "load_forecast", "patient_journey_aft", "patient_journey_hazard"} <= set(
        RELEASED
    )
    assert (MODELS / "README.md").exists()


def test_manifest_lists_every_shipped_file_with_its_sha256():
    listed = MANIFEST["files"]
    actual = shipped_files()
    assert set(listed) == set(actual)
    for relative, entry in listed.items():
        assert actual[relative].stat().st_size == entry["bytes"], relative
        assert sha256(actual[relative]) == entry["sha256"], relative
        assert entry["bytes"] <= MAX_FILE_BYTES, f"{relative} exceeds the 50 MB file limit"
    assert MANIFEST["total_bytes"] == sum(entry["bytes"] for entry in listed.values())


@pytest.mark.parametrize("name", RELEASED)
def test_artifact_files_are_byte_identical_to_the_checksummed_artifact(name):
    folder = MODELS / name
    spec = MANIFEST["models"][name]
    for native in spec["native_files"]:
        assert (folder / native).exists(), native
    if not (folder / "artifact-manifest.json").exists():
        assert name == "flow_quantile"
        return
    artifact_manifest = json.loads((folder / "artifact-manifest.json").read_text(encoding="utf-8"))
    assert spec["source"]["artifact_sha256"] == artifact_manifest["content_sha256"]
    for entry in artifact_manifest["files"]:
        path = folder / entry["path"]
        assert path.exists(), entry["path"]
        assert sha256(path) == entry["sha256"], f"{name}/{entry['path']} differs from the artifact"


@pytest.mark.parametrize("name", RELEASED)
def test_standalone_cli_reproduces_the_expected_predictions(name, tmp_path):
    folder = MODELS / name
    output = tmp_path / "predictions.csv"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    subprocess.run(
        [
            sys.executable,
            str(folder / "predict.py"),
            "--input",
            str(folder / "example.csv.gz"),
            "--output",
            str(output),
        ],
        check=True,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert_reproduced(name, read_csv(output), read_csv(folder / "example_expected.csv.gz"))


@pytest.mark.parametrize("name", RELEASED)
def test_python_api_and_joblib_bundle_reproduce_the_expected_predictions(name):
    folder = MODELS / name
    module = load_standalone(name)
    model = module.load(folder)
    frame = module.read_input(folder / "example.csv.gz", model)
    expected = read_csv(folder / "example_expected.csv.gz")
    assert_reproduced(name, module.predict(frame, model), expected)
    bundle_path = folder / "bundle.joblib"
    if not bundle_path.exists():
        assert name == "flow_quantile"
        return
    bundle = joblib.load(bundle_path)
    assert {"name", "version", "model", "features", "categories", "meta", "sha256_of_native_file"} <= set(bundle)
    assert bundle["name"] == name
    assert bundle["features"] == json.loads((folder / "features.json").read_text(encoding="utf-8"))["features"]
    digests = bundle["sha256_of_native_file"]
    digests = digests if isinstance(digests, dict) else {MANIFEST["models"][name]["native_files"][0]: digests}
    for native, digest in digests.items():
        assert MANIFEST["files"][f"{name}/{native}"]["sha256"] == digest
    assert_reproduced(name, module.predict(frame, module.from_bundle(bundle)), expected)


def test_flow_quantile_refit_was_verified_against_the_published_quantiles():
    folder = MODELS / "flow_quantile"
    if not (folder / "verification.json").exists():
        pytest.skip("flow quantile boosters are not shipped")
    verification = json.loads((folder / "verification.json").read_text(encoding="utf-8"))
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    for target, info in meta["targets"].items():
        if info["exported"]:
            assert verification[target]["within_tolerance"]
            assert verification[target]["hospital_sample_200_series"]["series"] == 200
