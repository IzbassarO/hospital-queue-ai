#!/usr/bin/env python3
"""Ingest: data/raw CSV -> DuckDB -> data/processed/*.parquet -> Postgres.

Run:  make ingest          (applies Alembic migrations first)
      PYTHONPATH=ml .venv/bin/python ml/pipelines/ingest.py [--skip-load]

Writes:
  data/processed/<table>.parquet, data/processed/_manifest.json
  ml/configs/regions.yaml           (region code dictionary, manual overrides preserved)
  reports/01_org_matching.csv       (fuzzy hospital <-> ERSB matches for review)
Reads:
  ml/configs/org_matches.yaml       (manual hospital <-> ERSB accept/reject overrides)
data/raw is only read.
"""
import argparse
import datetime as dt
import json
import shutil
import sys
import time

import duckdb

from hqai_ml.ingest import aggregates, dictionaries, facts, sources, staging
from hqai_ml.ingest.config import IngestSettings
from hqai_ml.ingest.load_postgres import LOAD_ORDER, load_all

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-load", action="store_true", help="only build Parquet, do not touch Postgres")
    args = ap.parse_args()

    settings = IngestSettings()
    params = settings.params()
    out = settings.processed_dir
    out.mkdir(parents=True, exist_ok=True)
    work_db = out / "_work.duckdb"
    work_db.unlink(missing_ok=True)
    spill = out / "_spill"
    manifest: dict = {"started_at": dt.datetime.now().isoformat(timespec="seconds"), "params": params.model_dump(mode="json"),
                      "sources": {}, "tables": {}}

    con = duckdb.connect(str(work_db))
    con.execute(f"SET memory_limit='{settings.duckdb_memory_limit}'")
    con.execute(f"SET temp_directory='{spill}'")
    staging.create_macros(con)

    # ---- sources
    src = {n: sources.find_sources(settings.raw_dir, n) for n in (1, 2, 3, 4)}
    for n, s in src.items():
        manifest["sources"][f"dataset_{n}"] = {"files": [p.name for p in s.valid], "skipped": s.skipped}
        for sk in s.skipped:
            log(f"WARNING dataset {n}: skipping {sk['file']} — {sk['reason']}")
    for table, n in (("raw_referral", 1), ("raw_refusal", 3), ("raw_ersb", 4)):
        rows = sources.stage_csv(con, table, src[n])
        manifest["sources"][f"dataset_{n}"]["rows"] = rows
        log(f"staged dataset {n} -> {table}: {rows:,} rows from {len(src[n].valid)} file(s)")
    paths = "[" + ", ".join("'" + str(p).replace("'", "''") + "'" for p in src[2].valid) + "]"
    waiting_codes = [r[0] for r in con.execute(
        f"SELECT DISTINCT trim(region_origin_code) FROM read_csv({paths}, header=true, all_varchar=true) ORDER BY 1"
    ).fetchall()]
    manifest["sources"]["dataset_2"]["region_codes"] = waiting_codes
    log(f"dataset 2: {len(waiting_codes)} distinct region_origin_code values")

    # ---- staging
    n_names = staging.build_name_map(con)
    log(f"name map: {n_names:,} distinct organization/region spellings normalized")
    staging.build_stg_referral(con)
    staging.build_stg_refusal(con)
    staging.build_stg_ersb(con)
    log("staging tables built")

    # ---- dictionaries
    dictionaries.build_dim_profile(con, params)
    manifest["dim_region"] = dictionaries.build_dim_region(con, params, settings.configs_dir / "regions.yaml", waiting_codes)
    log(f"dim_region: {manifest['dim_region']}")
    manifest["dim_organization"] = dictionaries.build_dim_organization(
        con, params, settings.reports_dir / "01_org_matching.csv", settings.configs_dir / "org_matches.yaml")
    log(f"dim_organization: {manifest['dim_organization']}")
    dictionaries.build_ersb_snapshot(con)

    # ---- facts + aggregates
    facts.build_fact_referral(con, params)
    facts.build_fact_admission_refusal(con)
    log("facts built")
    aggregates.build_agg_daily_hospital_profile(con, params)
    aggregates.build_agg_daily_region_profile(con)
    aggregates.build_agg_daily_admission_refusals(con)
    log("aggregates built")

    # ---- parquet
    for table in LOAD_ORDER:
        path = out / f"{table}.parquet"
        con.execute(f"COPY {table} TO '{path}' (FORMAT parquet, COMPRESSION zstd)")
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        manifest["tables"][table] = {"rows": rows, "parquet_mb": round(path.stat().st_size / 2**20, 1)}
        log(f"  parquet   {table:<30} {rows:>10,} rows  {manifest['tables'][table]['parquet_mb']:>7.1f} MB")
    con.close()
    work_db.unlink(missing_ok=True)
    shutil.rmtree(spill, ignore_errors=True)

    # ---- postgres
    if args.skip_load:
        manifest["postgres"] = {"loaded": False, "reason": "--skip-load"}
    else:
        log(f"loading into postgres {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db} …")
        manifest["postgres"] = {"loaded": True, "tables": load_all(out, settings.pg_conninfo, log=log)}

    manifest["finished_at"] = dt.datetime.now().isoformat(timespec="seconds")
    manifest["seconds"] = round(time.time() - T0, 1)
    (out / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    log(f"done — manifest: {out / '_manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
