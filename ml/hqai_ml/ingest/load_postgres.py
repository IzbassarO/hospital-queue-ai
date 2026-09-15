"""Load data/processed/*.parquet into Postgres (schema created by Alembic).

All tables are truncated and reloaded in ONE transaction: either the whole data layer is
replaced, or nothing changes. Rows are streamed Parquet -> Arrow batches -> CSV -> COPY,
so memory stays bounded regardless of table size.
"""

import io
import time
from pathlib import Path

import psycopg
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

# FK-safe order (parents first).
LOAD_ORDER = [
    "dim_region",
    "dim_profile",
    "dim_icd",
    "ersb_snapshot",
    "dim_organization",
    "fact_referral",
    "fact_admission_refusal",
    "agg_daily_hospital_profile",
    "agg_daily_region_profile",
    "agg_daily_admission_refusals",
]

_CSV_OPTIONS = pacsv.WriteOptions(include_header=False, batch_size=50_000)


def load_all(processed_dir: Path, conninfo: str, batch_rows: int = 100_000, log=print) -> dict[str, dict]:
    result: dict[str, dict] = {}
    with psycopg.connect(conninfo) as pg, pg.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(reversed(LOAD_ORDER)))
        for table in LOAD_ORDER:
            started = time.time()
            pf = pq.ParquetFile(processed_dir / f"{table}.parquet")
            columns = ", ".join(f'"{c}"' for c in pf.schema_arrow.names)
            with cur.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy:
                for batch in pf.iter_batches(batch_size=batch_rows):
                    buf = io.BytesIO()
                    pacsv.write_csv(batch, buf, write_options=_CSV_OPTIONS)
                    copy.write(buf.getbuffer())
            cur.execute(f"SELECT count(*) FROM {table}")
            loaded = cur.fetchone()[0]
            expected = pf.metadata.num_rows
            if loaded != expected:
                raise RuntimeError(f"{table}: loaded {loaded} rows, parquet has {expected}")
            result[table] = {"rows": loaded, "seconds": round(time.time() - started, 1)}
            log(f"  postgres  {table:<30} {loaded:>10,} rows  {result[table]['seconds']:>6.1f}s")
        cur.execute("ANALYZE")
        pg.commit()
    return result
