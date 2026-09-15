#!/usr/bin/env python3
"""Small Postgres fixture for the API tests in CI: a 2-region subset of the data layer and predictions.

  make fixture         build: read the current database -> backend/tests/fixtures/*.csv.gz + manifest.json
  make fixture-load    load:  fixture -> an EMPTY, migrated database (CI); then `make marts` builds the marts

The fixture holds only rows derived from the MoH open data already in Postgres (dictionaries, referrals, daily
aggregates) and model outputs computed from them (predictions, explanations, registry metrics) — no credentials,
no other sources. Everything the marts and the API read is included for the chosen regions; the marts themselves
are not, they are rebuilt from the fixture so `make marts` is exercised too. Budget: 5 MB in total.

Load refuses to run against a database that already has referrals unless --replace is given (it truncates the
data tables; decision_log is left alone).
"""

import argparse
import datetime as dt
import gzip
import hashlib
import json
import sys
from pathlib import Path

import psycopg
import yaml

from hqai_ml.ingest.config import REPO_ROOT, IngestSettings

FIXTURE_DIR = REPO_ROOT / "backend" / "tests" / "fixtures"
DEFAULT_REGIONS = ("62", "59")  # small regions whose high-load hospitals still have recommendation alternatives
MAX_BYTES = 5 * 1024 * 1024

# (table, SELECT for the subset) in foreign-key order; parameters: regions, since, test_start, test_end, as_of
TABLES: list[tuple[str, str]] = [
    ("dim_region", "SELECT * FROM dim_region"),
    ("dim_profile", "SELECT * FROM dim_profile"),
    (
        "ersb_snapshot",
        "SELECT e.* FROM ersb_snapshot e WHERE e.ersb_id IN "
        "(SELECT ersb_id FROM dim_organization WHERE region_code = ANY(%(regions)s))",
    ),
    ("dim_organization", "SELECT * FROM dim_organization WHERE region_code = ANY(%(regions)s)"),
    (
        # referrals of the subset hospitals that the marts / API read: registered or hospitalized since the start of
        # the card series, plus every referral with a test-period prediction
        "fact_referral",
        "SELECT f.* FROM fact_referral f JOIN dim_organization o ON o.org_code = f.org_code "
        "WHERE o.region_code = ANY(%(regions)s) AND (f.registration_date >= %(since)s "
        "OR f.hospitalization_date >= %(since)s OR f.referral_id IN (SELECT referral_id FROM pred_referral p "
        "WHERE p.org_code = f.org_code AND p.registration_date BETWEEN %(test_start)s AND %(test_end)s))",
    ),
    (
        "agg_daily_hospital_profile",
        "SELECT a.* FROM agg_daily_hospital_profile a JOIN dim_organization o ON o.org_code = a.org_code "
        "WHERE o.region_code = ANY(%(regions)s) AND a.date >= %(since)s",
    ),
    (
        "agg_daily_region_profile",
        "SELECT * FROM agg_daily_region_profile WHERE region_code = ANY(%(regions)s) AND date >= %(since)s",
    ),
    (
        "pred_referral",
        "SELECT p.* FROM pred_referral p JOIN dim_organization o ON o.org_code = p.org_code "
        "WHERE o.region_code = ANY(%(regions)s) AND p.registration_date BETWEEN %(test_start)s AND %(test_end)s",
    ),
    (
        "pred_daily_forecast",
        "SELECT * FROM pred_daily_forecast WHERE region_code = ANY(%(regions)s) AND origin_date = %(as_of)s",
    ),
    ("model_registry", "SELECT * FROM model_registry WHERE is_current"),
]
TRUNCATE_ON_REPLACE = [t for t, _ in TABLES] + [
    "fact_admission_refusal",
    "agg_daily_admission_refusals",
    "mart_hospital_profile_status",
    "mart_region_profile_status",
    "mart_area_status",
    "mart_build_info",
]


def _dates(settings: IngestSettings) -> dict[str, dt.date]:
    serving = yaml.safe_load((settings.configs_dir / "serving.yaml").read_text(encoding="utf-8"))
    split = yaml.safe_load((settings.configs_dir / "models.yaml").read_text(encoding="utf-8"))["split"]
    return {
        "since": serving["series_start"],
        "test_start": split["test_start"],
        "test_end": split["test_end"],
        "as_of": serving["as_of_date"],
    }


def build(settings: IngestSettings, regions: list[str], out_dir: Path) -> int:
    params = {"regions": regions, **_dates(settings)}
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "description": "2-region test fixture for CI (tools/test_fixture.py); MoH open data and model outputs only",
        "regions": regions,
        **{k: str(v) for k, v in params.items() if k != "regions"},
        "tables": [],
    }
    total = 0
    out_dir = out_dir.resolve()
    with psycopg.connect(settings.pg_conninfo) as con, psycopg.ClientCursor(con) as cur:
        for table, select in TABLES:
            sql = cur.mogrify(select, params)
            path = out_dir / f"{table}.csv.gz"
            # mtime=0 and no file name in the header: rebuilding unchanged data gives byte-identical files
            with (
                path.open("wb") as raw,
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as fh,
                cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)") as copy,
            ):
                for chunk in copy:
                    fh.write(chunk)
            rows = cur.execute(f"SELECT count(*) FROM ({sql}) t").fetchone()[0]
            size = path.stat().st_size
            total += size
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest["tables"].append(
                {"table": table, "file": path.name, "rows": rows, "bytes": size, "sha256": digest}
            )
            print(f"  {table:<28} {rows:>8,} rows  {size / 1024:>8.1f} KB")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  total {total / 1024 / 1024:.2f} MB -> {out_dir.relative_to(REPO_ROOT)}")
    if total > MAX_BYTES:
        print(f"fixture is {total / 1024 / 1024:.2f} MB, over the 5 MB budget: choose smaller regions", file=sys.stderr)
        return 1
    return 0


def load(settings: IngestSettings, in_dir: Path, replace: bool) -> int:
    manifest = json.loads((in_dir / "manifest.json").read_text(encoding="utf-8"))
    with psycopg.connect(settings.pg_conninfo) as con, con.cursor() as cur:
        if cur.execute("SELECT EXISTS (SELECT 1 FROM fact_referral)").fetchone()[0]:
            if not replace:
                print(
                    f"database {settings.postgres_db!r} already has referrals; refusing to load the fixture "
                    "(pass --replace to truncate the data tables)",
                    file=sys.stderr,
                )
                return 2
            cur.execute(f"TRUNCATE {', '.join(TRUNCATE_ON_REPLACE)}")
        for entry in manifest["tables"]:
            path = in_dir / entry["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                raise RuntimeError(f"{path.name}: checksum differs from manifest.json")
            with gzip.open(path, "rb") as fh:
                columns = fh.readline().decode("utf-8").strip()
                with cur.copy(f"COPY {entry['table']} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
                    while chunk := fh.read(1 << 20):
                        copy.write(chunk)
            loaded = cur.execute(f"SELECT count(*) FROM {entry['table']}").fetchone()[0]
            if loaded != entry["rows"]:
                raise RuntimeError(f"{entry['table']}: loaded {loaded} rows, manifest says {entry['rows']}")
            print(f"  {entry['table']:<28} {loaded:>8,} rows")
        for table, column in (("fact_referral", "referral_id"), ("pred_referral", "referral_id")):
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                f"coalesce((SELECT max({column}) FROM {table}), 1))"
            )
        con.commit()
    print(f"  fixture loaded into {settings.postgres_db!r} (regions {', '.join(manifest['regions'])})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="current database -> fixture files")
    b.add_argument("--regions", nargs="+", default=list(DEFAULT_REGIONS))
    b.add_argument("--out", type=Path, default=FIXTURE_DIR)
    ld = sub.add_parser("load", help="fixture files -> empty, migrated database")
    ld.add_argument("--dir", type=Path, default=FIXTURE_DIR)
    ld.add_argument("--replace", action="store_true", help="truncate the data tables of a non-empty database first")
    args = parser.parse_args()
    settings = IngestSettings()
    if args.command == "build":
        return build(settings, args.regions, args.out)
    return load(settings, args.dir, args.replace)


if __name__ == "__main__":
    sys.exit(main())
