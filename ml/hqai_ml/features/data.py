"""DuckDB access to the data layer (data/processed/*.parquet)."""
from pathlib import Path

import duckdb

TABLES = [
    "dim_region", "dim_profile", "dim_organization", "ersb_snapshot", "fact_referral",
    "fact_admission_refusal", "agg_daily_hospital_profile", "agg_daily_region_profile",
    "agg_daily_admission_refusals",
]


def connect(processed_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for t in TABLES:
        path = processed_dir / f"{t}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing — run `make ingest` first")
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{path}')")
    return con


def display_lookups(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, str]]:
    """Human-readable names for categorical codes (stored with model artifacts for explanations)."""
    from hqai_ml.ingest.normalize import short_org_name

    return {
        "region": dict(con.execute("SELECT region_code, region_name FROM dim_region").fetchall()),
        "profile": dict(con.execute("SELECT profile_code, profile_name FROM dim_profile").fetchall()),
        "org": {code: short_org_name(name) for code, name in
                con.execute("SELECT org_code, org_name FROM dim_organization").fetchall()},
    }
