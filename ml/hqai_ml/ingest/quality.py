"""Data-quality gateway between the cleaned DuckDB tables and data/processed/*.parquet.

Every table that becomes Parquet (and later Postgres) has an explicit contract here: required columns and type
families, code formats, a plausibility window for dates, ordering between registration and outcome, duplicate
counts and the day-hospital share. The gateway runs the rules in SQL inside the ingest connection, writes
`_quality_report.json` (counts per rule, pass/fail, thresholds) and raises `QualityGateError` on a hard violation
before any Parquet file is written, so a broken refresh never replaces the previous data layer.

Two modes share one implementation: `gate(con, ...)` inside `ml/pipelines/ingest.py` may repair (out-of-window
dates in rows no upstream rule already flagged are counted and set to NULL, implausible durations likewise), and
`check_processed(...)` opens read-only views over the existing Parquet files and only counts. Day-hospital profiles
(`DH`) are classified and their share reported, never filtered: the accepted evidence includes them.

Thresholds come from an optional `quality:` section of ml/configs/ingest.yaml; without it the module constants apply.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml
from pydantic import BaseModel

from hqai_ml.ingest.config import IngestParams

DEFAULT_THRESHOLDS = {
    "max_out_of_window_date_share": 0.01,
    "max_null_code_share": 0.0,
    "max_unflagged_order_violations": 0,
    "max_duplicate_key_rows": 0,
}
REGION_CODE_PATTERN = "^[0-9]{2}$"
CODE_LENGTH_HINT = {"region_code": 2}
FAMILIES = {
    "date": {"DATE"},
    "timestamp": {"TIMESTAMP", "TIMESTAMP WITH TIME ZONE", "TIMESTAMP_NS", "TIMESTAMP_MS"},
    "int": {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT"},
    "float": {"FLOAT", "DOUBLE", "REAL"},
    "text": {"VARCHAR"},
    "bool": {"BOOLEAN"},
}


class Thresholds(BaseModel):
    max_out_of_window_date_share: float = DEFAULT_THRESHOLDS["max_out_of_window_date_share"]
    max_null_code_share: float = DEFAULT_THRESHOLDS["max_null_code_share"]
    max_unflagged_order_violations: int = DEFAULT_THRESHOLDS["max_unflagged_order_violations"]
    max_duplicate_key_rows: int = DEFAULT_THRESHOLDS["max_duplicate_key_rows"]


def load_thresholds(configs_dir: Path) -> tuple[Thresholds, str]:
    """(thresholds, provenance): the `quality:` section of ingest.yaml when present, else module constants."""
    raw = yaml.safe_load((configs_dir / "ingest.yaml").read_text(encoding="utf-8")) or {}
    section = raw.get("quality")
    if isinstance(section, dict) and section:
        return Thresholds(**section), "ml/configs/ingest.yaml: quality"
    return Thresholds(), "module constants (ml/configs/ingest.yaml has no quality section)"


@dataclass(frozen=True)
class DateRule:
    column: str
    handled_flag: str | None = None  # rows already flagged upstream keep their value (planned_dt_raw, retro rows)


@dataclass(frozen=True)
class DurationRule:
    column: str
    minimum: int  # inclusive, in days
    maximum_span: bool = True  # maximum = length of the plausibility window in days


@dataclass(frozen=True)
class TableContract:
    columns: dict[str, str]  # column -> type family
    key: tuple[str, ...]  # unique key
    not_null: tuple[str, ...] = ()
    region_codes: tuple[str, ...] = ()  # columns that must match REGION_CODE_PATTERN when not null
    dates: tuple[DateRule, ...] = ()
    durations: tuple[DurationRule, ...] = ()
    order: tuple[tuple[str, str, str | None], ...] = ()  # (earlier, later, flag that legitimises later < earlier)
    dense: tuple[str, ...] = ()  # key columns of a dense calendar (rows == distinct keys x distinct dates)
    duplicate_code: tuple[str, str] | None = None  # (code column, flag column) counted, never removed
    profile_column: str | None = None  # column classified against the day-hospital code
    soft_null: tuple[str, ...] = ()  # nullable codes whose null share is reported only


CONTRACTS: dict[str, TableContract] = {
    "dim_region": TableContract(
        columns={
            "region_code": "text",
            "region_name": "text",
            "vote_region_name": "text",
            "vote_share": "float",
            "vote_referrals": "int",
            "runner_up_name": "text",
            "runner_up_share": "float",
            "is_ambiguous": "bool",
            "manual_override": "bool",
        },
        key=("region_code",),
        not_null=("region_code", "region_name"),
        region_codes=("region_code",),
    ),
    "dim_profile": TableContract(
        columns={
            "profile_code": "text",
            "profile_name": "text",
            "name_share": "float",
            "n_referrals": "int",
            "is_day_hospital": "bool",
        },
        key=("profile_code",),
        not_null=("profile_code", "profile_name", "is_day_hospital"),
        profile_column="profile_code",
    ),
    "dim_icd": TableContract(
        columns={"icd10_code": "text", "icd10_name": "text", "name_share": "float", "n_referrals": "int"},
        key=("icd10_code",),
        not_null=("icd10_code",),
    ),
    "ersb_snapshot": TableContract(
        columns={
            "ersb_id": "int",
            "org_name": "text",
            "org_key": "text",
            "discharged_total": "int",
            "bed_days": "int",
            "avg_length_of_stay": "float",
            "org_code": "text",
            "n_matched_org_codes": "int",
            "sdu_load_date": "timestamp",
        },
        key=("ersb_id",),
        not_null=("ersb_id", "org_name"),
        dates=(DateRule("sdu_load_date"),),
        soft_null=("org_code",),
    ),
    "dim_organization": TableContract(
        columns={
            "org_code": "text",
            "org_name": "text",
            "org_key": "text",
            "region_code": "text",
            "region_method": "text",
            "n_referrals": "int",
            "n_origin_regions": "int",
            "ersb_id": "int",
            "match_score": "float",
            "match_method": "text",
        },
        key=("org_code",),
        not_null=("org_code", "org_name", "region_code"),
        region_codes=("region_code",),
    ),
    "fact_referral": TableContract(
        columns={
            "referral_id": "int",
            "hospitalization_code": "text",
            "region_code": "text",
            "org_code": "text",
            "profile_code": "text",
            "is_dup_code": "bool",
            "hospital_region_code": "text",
            "registration_dt": "timestamp",
            "planned_dt_raw": "timestamp",
            "planned_dt": "timestamp",
            "polyclinic_dt": "timestamp",
            "hospitalization_dt": "timestamp",
            "refusal_dt": "timestamp",
            "sdu_load_date": "timestamp",
            "outcome": "text",
            "outcome_conflict": "bool",
            "registration_date": "date",
            "registration_weekday": "int",
            "planned_week": "date",
            "hospitalization_date": "date",
            "refusal_date": "date",
            "resolution_date": "date",
            "wait_days": "int",
            "wait_to_refusal_days": "int",
            "same_day_registration": "bool",
            "retro_registration": "bool",
            "planned_dt_out_of_range": "bool",
            "planned_lag_days": "int",
        },
        key=("referral_id",),
        not_null=("referral_id", "hospitalization_code", "region_code", "org_code", "profile_code", "registration_dt"),
        region_codes=("region_code", "hospital_region_code"),
        dates=(
            DateRule("registration_dt"),
            DateRule("registration_date"),
            DateRule("planned_dt_raw", handled_flag="planned_dt_out_of_range"),
            DateRule("planned_dt"),
            DateRule("planned_week"),
            DateRule("polyclinic_dt"),
            DateRule("hospitalization_dt", handled_flag="retro_registration"),
            DateRule("hospitalization_date", handled_flag="retro_registration"),
            DateRule("refusal_dt"),
            DateRule("refusal_date"),
            DateRule("resolution_date", handled_flag="retro_registration"),
            DateRule("sdu_load_date"),
        ),
        durations=(
            DurationRule("wait_days", 0),
            DurationRule("wait_to_refusal_days", 0),
            DurationRule("planned_lag_days", -10_000),
        ),
        order=(
            ("registration_dt", "hospitalization_dt", "retro_registration"),
            ("registration_dt", "refusal_dt", None),
        ),
        duplicate_code=("hospitalization_code", "is_dup_code"),
        profile_column="profile_code",
    ),
    "fact_admission_refusal": TableContract(
        columns={
            "refusal_id": "int",
            "source_part": "int",
            "region_code": "text",
            "org_code": "text",
            "org_match_method": "text",
            "refuse_dt": "timestamp",
            "refuse_date": "date",
            "attach_region_code": "text",
            "icd10_code": "text",
            "sdu_load_date": "timestamp",
        },
        key=("refusal_id",),
        not_null=("refusal_id", "refuse_dt", "refuse_date"),
        region_codes=("region_code", "attach_region_code"),
        dates=(DateRule("refuse_dt"), DateRule("refuse_date"), DateRule("sdu_load_date")),
        soft_null=("org_code", "region_code"),
    ),
    "agg_daily_hospital_profile": TableContract(
        columns={
            "date": "date",
            "org_code": "text",
            "profile_code": "text",
            "region_code": "text",
            "registrations": "int",
            "hospitalizations": "int",
            "refusals": "int",
            "queue_length": "int",
        },
        key=("date", "org_code", "profile_code"),
        not_null=("date", "org_code", "profile_code", "registrations", "hospitalizations", "refusals", "queue_length"),
        region_codes=("region_code",),
        dates=(DateRule("date"),),
        dense=("org_code", "profile_code"),
        profile_column="profile_code",
    ),
    "agg_daily_region_profile": TableContract(
        columns={
            "date": "date",
            "region_code": "text",
            "profile_code": "text",
            "registrations": "int",
            "hospitalizations": "int",
            "refusals": "int",
            "queue_length": "int",
        },
        key=("date", "region_code", "profile_code"),
        not_null=("date", "region_code", "profile_code", "registrations", "hospitalizations", "queue_length"),
        region_codes=("region_code",),
        dates=(DateRule("date"),),
        dense=("region_code", "profile_code"),
        profile_column="profile_code",
    ),
    "agg_daily_admission_refusals": TableContract(
        columns={"date": "date", "org_code": "text", "region_code": "text", "refusals": "int"},
        key=("date", "org_code"),
        not_null=("date", "org_code", "refusals"),
        region_codes=("region_code",),
        dates=(DateRule("date"),),
    ),
}
DATE_FAMILIES = {"date", "timestamp"}


class QualityGateError(RuntimeError):
    """Raised after the report is written when at least one hard rule fails."""


@dataclass
class Check:
    rule: str
    status: str  # PASS | FAIL | INFO
    count: int = 0
    share: float | None = None
    column: str | None = None
    action: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class TableResult:
    rows: int = 0
    checks: list[Check] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "FAIL" if any(c.status == "FAIL" for c in self.checks) else "PASS"


def _quote(column: str) -> str:
    return '"' + column.replace('"', '""') + '"'


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchone()[0]


def _column_types(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    rows = con.execute(f"SELECT column_name, column_type FROM (DESCRIBE {table})").fetchall()
    return {name: str(kind) for name, kind in rows}


def _family(duck_type: str) -> str | None:
    upper = duck_type.upper()
    if upper.startswith("DECIMAL"):
        return "float"
    return next((family for family, kinds in FAMILIES.items() if upper in kinds), None)


def _share(count: int, total: int) -> float:
    return round(count / total, 6) if total else 0.0


def _check_table(
    con: duckdb.DuckDBPyConnection,
    table: str,
    contract: TableContract,
    params: IngestParams,
    thresholds: Thresholds,
    enforce: bool,
) -> TableResult:
    result = TableResult()
    types = _column_types(con, table)
    missing = [c for c in contract.columns if c not in types]
    result.checks.append(
        Check("required_columns", "FAIL" if missing else "PASS", len(missing), detail=", ".join(missing) or None)
    )
    if missing:
        return result
    for column, family in contract.columns.items():
        actual = _family(types[column])
        if actual != family:
            result.checks.append(
                Check("column_type", "FAIL", 1, column=column, detail=f"expected {family}, got {types[column]}")
            )
    if any(c.rule == "column_type" for c in result.checks):
        return result
    result.checks.append(Check("column_types", "PASS", len(contract.columns)))

    result.rows = rows = int(_scalar(con, f"SELECT count(*) FROM {table}"))
    result.checks.append(Check("non_empty", "PASS" if rows else "FAIL", rows))
    if not rows:
        return result

    key = ", ".join(_quote(c) for c in contract.key)
    duplicate_rows = rows - int(_scalar(con, f"SELECT count(*) FROM (SELECT DISTINCT {key} FROM {table})"))
    result.checks.append(
        Check(
            "unique_key",
            "PASS" if duplicate_rows <= thresholds.max_duplicate_key_rows else "FAIL",
            duplicate_rows,
            column=",".join(contract.key),
        )
    )
    for column in contract.not_null:
        nulls = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {_quote(column)} IS NULL"))
        result.checks.append(
            Check(
                "not_null",
                "PASS" if _share(nulls, rows) <= thresholds.max_null_code_share else "FAIL",
                nulls,
                _share(nulls, rows),
                column,
            )
        )
    for column in contract.soft_null:
        nulls = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {_quote(column)} IS NULL"))
        result.checks.append(Check("nullable_code_share", "INFO", nulls, _share(nulls, rows), column))
    for column in contract.region_codes:
        bad = int(
            _scalar(
                con,
                f"SELECT count(*) FROM {table} WHERE {_quote(column)} IS NOT NULL "
                f"AND NOT regexp_matches({_quote(column)}, ?)",
                [REGION_CODE_PATTERN],
            )
        )
        result.checks.append(
            Check(
                "region_code_format",
                "PASS" if bad == 0 else "FAIL",
                bad,
                _share(bad, rows),
                column,
                detail=f"{CODE_LENGTH_HINT['region_code']} digits",
            )
        )

    lo, hi_exclusive = params.planned_dt_min, params.planned_dt_max + dt.timedelta(days=1)
    for rule in contract.dates:
        col = _quote(rule.column)
        outside = f"({col} < ? OR {col} >= ?)"
        non_null = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {col} IS NOT NULL"))
        total_out = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {outside}", [lo, hi_exclusive]))
        if rule.handled_flag:
            flagged = int(
                _scalar(
                    con,
                    f"SELECT count(*) FROM {table} WHERE {outside} AND coalesce({_quote(rule.handled_flag)}, false)",
                    [lo, hi_exclusive],
                )
            )
            result.checks.append(
                Check(
                    "date_out_of_window_handled",
                    "INFO",
                    flagged,
                    _share(flagged, non_null),
                    rule.column,
                    action="kept",
                    detail=f"already flagged by {rule.handled_flag}",
                )
            )
            unflagged_sql = f"{outside} AND NOT coalesce({_quote(rule.handled_flag)}, false)"
        else:
            flagged = 0
            unflagged_sql = outside
        unflagged = total_out - flagged
        share = _share(unflagged, non_null)
        hard = share > thresholds.max_out_of_window_date_share
        action = None
        if unflagged and not hard:
            action = "nulled" if enforce else "would be nulled"
            if enforce:
                con.execute(f"UPDATE {table} SET {col} = NULL WHERE {unflagged_sql}", [lo, hi_exclusive])
        result.checks.append(
            Check(
                "date_out_of_window",
                "FAIL" if hard else "PASS",
                unflagged,
                share,
                rule.column,
                action=action,
                detail=f"window [{lo}, {params.planned_dt_max}]",
            )
        )
    span_days = (params.planned_dt_max - params.planned_dt_min).days
    for rule in contract.durations:
        col = _quote(rule.column)
        condition = f"({col} < ? OR {col} > ?)"
        bad = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {condition}", [rule.minimum, span_days]))
        action = None
        if bad:
            action = "nulled" if enforce else "would be nulled"
            if enforce:
                con.execute(f"UPDATE {table} SET {col} = NULL WHERE {condition}", [rule.minimum, span_days])
        result.checks.append(
            Check(
                "duration_implausible",
                "PASS",
                bad,
                _share(bad, rows),
                rule.column,
                action=action,
                detail=f"outside [{rule.minimum}, {span_days}] days",
            )
        )
    for earlier, later, flag in contract.order:
        e, l_ = _quote(earlier), _quote(later)
        violations = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {l_} < {e}"))
        if flag:
            unflagged = int(
                _scalar(con, f"SELECT count(*) FROM {table} WHERE {l_} < {e} AND NOT coalesce({_quote(flag)}, false)")
            )
            result.checks.append(
                Check(
                    "order_violation_handled",
                    "INFO",
                    violations - unflagged,
                    _share(violations - unflagged, rows),
                    f"{earlier} <= {later}",
                    action="kept",
                    detail=f"already flagged by {flag}",
                )
            )
        else:
            unflagged = violations
        result.checks.append(
            Check(
                "order_violation",
                "PASS" if unflagged <= thresholds.max_unflagged_order_violations else "FAIL",
                unflagged,
                _share(unflagged, rows),
                f"{earlier} <= {later}",
            )
        )
    if contract.duplicate_code:
        code, flag = contract.duplicate_code
        extra = rows - int(_scalar(con, f"SELECT count(*) FROM (SELECT DISTINCT {_quote(code)} FROM {table})"))
        flagged = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE coalesce({_quote(flag)}, false)"))
        consistent = int(
            _scalar(
                con,
                f"SELECT count(*) FROM (SELECT {_quote(code)}, count(*) > 1 AS dup, "
                f"bool_and({_quote(flag)}) AS flagged FROM {table} GROUP BY 1) WHERE dup <> flagged",
            )
        )
        result.checks.append(
            Check(
                "duplicate_codes",
                "PASS" if consistent == 0 else "FAIL",
                extra,
                _share(extra, rows),
                code,
                action="kept",
                detail=f"{flagged} rows flagged by {flag}; {consistent} codes with an inconsistent flag",
            )
        )
    if contract.dense:
        keys = ", ".join(_quote(c) for c in contract.dense)
        distinct_keys = int(_scalar(con, f"SELECT count(*) FROM (SELECT DISTINCT {keys} FROM {table})"))
        distinct_dates = int(_scalar(con, f'SELECT count(DISTINCT "date") FROM {table}'))
        window_days = (params.window_end - params.window_start).days + 1
        ok = rows == distinct_keys * distinct_dates == distinct_keys * window_days
        result.checks.append(
            Check(
                "dense_calendar",
                "PASS" if ok else "FAIL",
                rows,
                detail=f"{distinct_keys} series x {distinct_dates} days, window {window_days} days",
            )
        )
    if contract.profile_column:
        col = _quote(contract.profile_column)
        day_hospital = int(_scalar(con, f"SELECT count(*) FROM {table} WHERE {col} = ?", [params.day_hospital_code]))
        result.checks.append(
            Check(
                "day_hospital_share",
                "INFO",
                day_hospital,
                _share(day_hospital, rows),
                contract.profile_column,
                action="kept",
                detail=f"profile {params.day_hospital_code} ({params.day_hospital_name}) classified, not filtered",
            )
        )
        if table == "dim_profile":
            wrong = int(
                _scalar(
                    con,
                    f"SELECT count(*) FROM {table} WHERE is_day_hospital <> ({col} = ?)",
                    [params.day_hospital_code],
                )
            )
            result.checks.append(
                Check(
                    "day_hospital_flag",
                    "PASS" if wrong == 0 else "FAIL",
                    wrong,
                    column=contract.profile_column,
                    detail="is_day_hospital must be true exactly for the day-hospital code",
                )
            )
    return result


def run_gateway(
    con: duckdb.DuckDBPyConnection,
    params: IngestParams,
    thresholds: Thresholds,
    *,
    enforce: bool,
    tables: list[str] | None = None,
    thresholds_source: str = "module constants",
    source: str = "ingest",
) -> dict:
    """Apply every contract; returns the report (status PASS/FAIL, hard violations listed) without raising."""
    names = tables or list(CONTRACTS)
    unknown = sorted(set(names) - set(CONTRACTS))
    if unknown:
        raise ValueError(f"tables without a quality contract: {unknown}")
    report_tables: dict[str, dict] = {}
    hard: list[str] = []
    for table in names:
        result = _check_table(con, table, CONTRACTS[table], params, thresholds, enforce)
        report_tables[table] = {
            "status": result.status,
            "rows": result.rows,
            "checks": [c.as_dict() for c in result.checks],
        }
        hard.extend(
            f"{table}.{c.column}: {c.rule} count={c.count}" if c.column else f"{table}: {c.rule} count={c.count}"
            for c in result.checks
            if c.status == "FAIL"
        )
    return {
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "enforce" if enforce else "check",
        "source": source,
        "status": "FAIL" if hard else "PASS",
        "thresholds": thresholds.model_dump(),
        "thresholds_source": thresholds_source,
        "date_window": {"min": params.planned_dt_min.isoformat(), "max": params.planned_dt_max.isoformat()},
        "day_hospital_code": params.day_hospital_code,
        "hard_violations": hard,
        "tables": report_tables,
    }


def write_report(report: dict, path: Path) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def gate(
    con: duckdb.DuckDBPyConnection,
    params: IngestParams,
    configs_dir: Path,
    report_path: Path | None,
    *,
    enforce: bool,
    tables: list[str] | None = None,
    source: str = "ingest",
) -> dict:
    """Run the gateway, persist the report when a path is given, then fail the run on hard violations."""
    thresholds, provenance = load_thresholds(configs_dir)
    report = run_gateway(
        con, params, thresholds, enforce=enforce, tables=tables, thresholds_source=provenance, source=source
    )
    if report_path is not None:
        write_report(report, report_path)
    if report["status"] != "PASS":
        where = f"; report: {report_path}" if report_path else ""
        raise QualityGateError("data-quality gateway failed: " + "; ".join(report["hard_violations"]) + where)
    return report


def check_processed(processed_dir: Path, params: IngestParams, configs_dir: Path, report_path: Path | None) -> dict:
    """Read-only run over data/processed/*.parquet through DuckDB views; nothing under processed_dir is written."""
    con = duckdb.connect()
    present = []
    for table in CONTRACTS:
        path = processed_dir / f"{table}.parquet"
        if not path.exists():
            continue
        # DuckDB cannot bind a parameter inside CREATE VIEW, so the path is inlined with doubled quotes.
        literal = str(path).replace("'", "''")
        con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{literal}')")
        present.append(table)
    if not present:
        raise FileNotFoundError(f"no contracted Parquet tables under {processed_dir}")
    try:
        return gate(con, params, configs_dir, report_path, enforce=False, tables=present, source=str(processed_dir))
    finally:
        con.close()
