"""Model artifact registry on disk.

artifacts/models/<model_name>/<YYYYMMDD-HHMM>/   model files, features.json, categories.json,
                                                   meta.json (training window, params), metrics.json
artifacts/models/manifest.json                     {model_name: {"current": version, "path": ...}}
"""
import datetime as dt
import json
from pathlib import Path

import lightgbm as lgb

MANIFEST = "manifest.json"


def _root(artifacts_dir: Path) -> Path:
    return artifacts_dir / "models"


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def read_manifest(artifacts_dir: Path) -> dict:
    path = _root(artifacts_dir) / MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(artifacts_dir: Path, model_name: str, boosters: dict[str, lgb.Booster], *, features: list[str],
         categories: dict, meta: dict, metrics: dict, extra: dict[str, object] | None = None,
         make_current: bool = True) -> tuple[str, Path]:
    """Write a new version directory; returns (version, path)."""
    now = dt.datetime.now()
    version = now.strftime("%Y%m%d-%H%M")
    base = _root(artifacts_dir) / model_name
    path, i = base / version, 2
    while path.exists():  # two runs within the same minute
        version = f"{now:%Y%m%d-%H%M}-{i}"
        path, i = base / version, i + 1
    path.mkdir(parents=True)
    for fname, booster in boosters.items():
        booster.save_model(str(path / fname))
    _dump(path / "features.json", {"features": features, "categorical": list(categories)})
    _dump(path / "categories.json", categories)
    _dump(path / "meta.json", {"model_name": model_name, "version": version, "trained_at": now.isoformat(timespec="seconds"),
                               "model_files": list(boosters), **meta})
    _dump(path / "metrics.json", metrics)
    for fname, obj in (extra or {}).items():
        _dump(path / fname, obj)
    if make_current:
        set_current(artifacts_dir, model_name, version)
    return version, path


def set_current(artifacts_dir: Path, model_name: str, version: str) -> None:
    manifest = read_manifest(artifacts_dir)
    manifest[model_name] = {"current": version, "path": f"models/{model_name}/{version}",
                            "updated_at": dt.datetime.now().isoformat(timespec="seconds")}
    _dump(_root(artifacts_dir) / MANIFEST, manifest)


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
    """Everything in a version directory: boosters, features, categories, meta, metrics, extras."""
    path = version_dir(artifacts_dir, model_name, version)
    meta = load_json(path, "meta.json")
    out = {
        "path": path,
        "meta": meta,
        "version": meta["version"],
        "boosters": {f: lgb.Booster(model_file=str(path / f)) for f in meta["model_files"]},
        "features": load_json(path, "features.json")["features"],
        "categories": load_json(path, "categories.json"),
        "metrics": load_json(path, "metrics.json"),
    }
    for extra in path.glob("*.json"):
        if extra.name not in {"meta.json", "features.json", "categories.json", "metrics.json"}:
            out[extra.stem] = load_json(path, extra.name)
    return out
