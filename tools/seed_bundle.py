#!/usr/bin/env python3
"""Build seed/ — the committed demo seed that `make demo` loads into the database of a fresh clone.

  make seed-build      current database + artifacts -> seed/ (tables, publish bundles, manifest.json)

The seed carries what the product reads at run time: the national dictionaries, daily aggregates, serving marts and
model registry as gzipped CSV (COPY ... TO STDOUT ordered by primary key, gzip without timestamp or file name, so a
rebuild of unchanged data is byte-identical); the six accepted publish bundles (Model Assurance, operational
intelligence, review evidence, waiting list, per-referral estimates, verification worklist) byte-for-byte as they
were published, so their
identities do not change; and the referrals, per-referral predictions and daily forecasts of the same two regions as
tools/test_fixture.py, so the legacy referral endpoints and hospital cards work there. No raw MoH files and no
credentials are copied; the full pipeline (`make ingest predict marts` and the publish targets) reproduces every row
from the open data. Budget: 40 MB.

Each bundle's raw SHA-256 must equal bundle_sha256 of the active snapshot in the database: the seed reproduces the
publication that is actually serving, not a later rebuild of the same evidence.
"""

import argparse
import datetime as dt
import gzip
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
import test_fixture

from hqai_ml.ingest.config import REPO_ROOT, IngestSettings

SEED_DIR = REPO_ROOT / "seed"
ARTIFACTS_DIR = REPO_ROOT / "artifacts"
MAX_BYTES = 40 * 1024 * 1024

# whole tables (all 20 regions), in the order the loader inserts them; the 2-region slice comes from the fixture SELECTs
LOAD_ORDER = (
    "dim_region",
    "dim_profile",
    "dim_icd",
    "ersb_snapshot",
    "dim_organization",
    "fact_referral",
    "agg_daily_hospital_profile",
    "agg_daily_region_profile",
    "agg_daily_admission_refusals",
    "pred_referral",
    "pred_daily_forecast",
    "model_registry",
    "mart_hospital_profile_status",
    "mart_region_profile_status",
    "mart_area_status",
    "mart_build_info",
)
SLICED_TABLES = ("fact_referral", "pred_referral", "pred_daily_forecast")
SLICED_SELECTS = {table: select for table, select in test_fixture.TABLES if table in SLICED_TABLES}
SNAPSHOT_COUNT_COLUMNS = (
    "capability_count",
    "forecast_count",
    "signal_count",
    "scenario_count",
    "scenario_entity_count",
    "scenario_cell_count",
    "alternative_set_count",
    "alternative_count",
    "hospital_count",
    "waiting_count",
    "referral_count",
)


@dataclass(frozen=True)
class BundleSpec:
    kind: str  # also the artifacts/ sub-directory and the JSON file stem
    snapshot_table: str
    id_column: str
    identity_column: str
    compress: bool

    @property
    def file_name(self) -> str:
        return f"{self.kind}.json.gz" if self.compress else f"{self.kind}.json"


BUNDLES = (
    BundleSpec("model_assurance", "model_assurance_snapshot", "assurance_id", "assurance_identity_sha256", False),
    BundleSpec(
        "operational_intelligence",
        "operational_intelligence_snapshot",
        "publication_id",
        "publication_identity_sha256",
        True,
    ),
    BundleSpec("review_evidence", "review_evidence_snapshot", "publication_id", "publication_identity_sha256", True),
    BundleSpec("waiting_list", "waiting_list_snapshot", "publication_id", "publication_identity_sha256", True),
    BundleSpec(
        "referral_estimates",
        "referral_estimate_snapshot",
        "publication_id",
        "publication_identity_sha256",
        True,
    ),
    BundleSpec(
        "verification_worklist",
        "verification_worklist_snapshot",
        "publication_id",
        "publication_identity_sha256",
        True,
    ),
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _display(path: Path) -> str:
    """Repository-relative when the path lies inside the repository (the default seed/), otherwise absolute."""
    return str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)


def _primary_key(cur: psycopg.Cursor, table: str) -> list[str]:
    rows = cur.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY array_position(i.indkey::int2[], a.attnum)",
        (table,),
    ).fetchall()
    if not rows:
        raise RuntimeError(f"{table}: no primary key, cannot order deterministically")
    return [row[0] for row in rows]


def _table_select(cur: psycopg.ClientCursor, table: str, params: dict) -> str:
    """SELECT for one table: the whole table, or the fixture's 2-region subset, ordered by primary key."""
    order = ", ".join(_primary_key(cur, table))
    if table in SLICED_SELECTS:
        return f"SELECT * FROM ({cur.mogrify(SLICED_SELECTS[table], params)}) t ORDER BY {order}"
    return f"SELECT * FROM {table} ORDER BY {order}"


def _gzip_writer(path: Path):
    # mtime=0 and no file name in the header: unchanged content gives byte-identical files
    raw = path.open("wb")
    return raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0)


def export_table(cur: psycopg.ClientCursor, table: str, params: dict, path: Path) -> dict:
    sql = _table_select(cur, table, params)
    raw, fh = _gzip_writer(path)
    with raw, fh, cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)") as copy:
        for chunk in copy:
            fh.write(chunk)
    rows = cur.execute(f"SELECT count(*) FROM ({sql}) t").fetchone()[0]
    return {
        "table": table,
        "file": f"tables/{path.name}",
        "scope": "regions" if table in SLICED_TABLES else "national",
        "rows": rows,
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
    }


def _active_snapshot(cur: psycopg.Cursor, spec: BundleSpec) -> dict:
    row = cur.execute(f"SELECT row_to_json(s) FROM {spec.snapshot_table} s WHERE is_active").fetchone()
    if row is None:
        raise RuntimeError(f"{spec.snapshot_table}: no active snapshot; publish the bundle first")
    return row[0]


def export_bundle(cur: psycopg.Cursor, spec: BundleSpec, out_dir: Path) -> dict:
    snapshot = _active_snapshot(cur, spec)
    publication_id = snapshot[spec.id_column]
    source = ARTIFACTS_DIR / spec.kind / publication_id / f"{spec.kind}.json"
    if not source.is_file():
        raise RuntimeError(f"{source.relative_to(REPO_ROOT)}: bundle file of the active snapshot not found")
    raw_sha256 = sha256_of(source)
    if raw_sha256 != snapshot["bundle_sha256"]:
        raise RuntimeError(
            f"{source.relative_to(REPO_ROOT)}: SHA-256 {raw_sha256[:12]}… differs from the published bundle "
            f"{snapshot['bundle_sha256'][:12]}…; the seed must carry the bytes that were published"
        )
    target = out_dir / spec.file_name
    if spec.compress:
        raw, fh = _gzip_writer(target)
        with source.open("rb") as src, raw, fh:
            shutil.copyfileobj(src, fh, 1 << 20)
    else:
        shutil.copyfile(source, target)
    entry = {
        "kind": spec.kind,
        "file": spec.file_name,
        "bytes": target.stat().st_size,
        "sha256": sha256_of(target),
        "raw_bytes": source.stat().st_size,
        "raw_sha256": raw_sha256,
        "publication_id": publication_id,
        "identity_sha256": snapshot[spec.identity_column],
        "source_code_commit": snapshot["source_code_commit"],
        "generated_at": snapshot["generated_at"],
        "counts": {key: snapshot[key] for key in SNAPSHOT_COUNT_COLUMNS if key in snapshot},
    }
    for key in ("current_origin", "origin"):
        if key in snapshot:
            entry["current_origin"] = snapshot[key]
    if "source_provenance" in snapshot:
        entry["source_runs"] = {key: value.get("run_id") for key, value in snapshot["source_provenance"].items()}
    return entry


def build(settings: IngestSettings, regions: list[str], out_dir: Path) -> int:
    dates = test_fixture._dates(settings)
    params = {"regions": regions, **dates}
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "description": "demo seed for `make demo` (tools/seed_bundle.py): MoH open-data derived tables and the "
        "accepted publish bundles; no raw MoH files, no credentials",
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "as_of_date": str(dates["as_of"]),
        "slice": {
            "tables": list(SLICED_TABLES),
            "regions": regions,
            "note": "these tables hold only the listed regions (referrals and predictions since series_start, "
            "test-period predictions, forecasts from the serving origin); every other table is national",
            **{key: str(value) for key, value in dates.items() if key != "as_of"},
        },
        "tables": [],
        "bundles": [],
    }
    produced: set[Path] = set()
    with psycopg.connect(settings.pg_conninfo) as con, psycopg.ClientCursor(con) as cur:
        for table in LOAD_ORDER:
            path = tables_dir / f"{table}.csv.gz"
            entry = export_table(cur, table, params, path)
            produced.add(path)
            manifest["tables"].append(entry)
            print(f"  {table:<30} {entry['rows']:>9,} rows  {entry['bytes'] / 1024:>9.1f} KB  {entry['scope']}")
        for spec in BUNDLES:
            entry = export_bundle(cur, spec, out_dir)
            produced.add(out_dir / spec.file_name)
            manifest["bundles"].append(entry)
            print(
                f"  {spec.file_name:<30} {entry['raw_bytes'] / 1024 / 1024:>7.1f} MB raw "
                f"{entry['bytes'] / 1024:>9.1f} KB  {entry['publication_id']}  {entry['identity_sha256'][:8]}…"
            )
    for stale in sorted(p for p in tables_dir.glob("*.csv.gz") if p not in produced):
        stale.unlink()
        print(f"  removed stale {stale.relative_to(out_dir)}")
    total = sum(e["bytes"] for e in manifest["tables"]) + sum(e["bytes"] for e in manifest["bundles"])
    manifest["total_bytes"] = total
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  total {total / 1024 / 1024:.2f} MB -> {_display(out_dir)}/")
    if total > MAX_BYTES:
        print(f"seed is {total / 1024 / 1024:.2f} MB, over the {MAX_BYTES // 1024 // 1024} MB budget", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--regions", nargs="+", default=list(test_fixture.DEFAULT_REGIONS))
    parser.add_argument("--out", type=Path, default=SEED_DIR)
    args = parser.parse_args()
    return build(IngestSettings(), args.regions, args.out.resolve())


if __name__ == "__main__":
    sys.exit(main())
