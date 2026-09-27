"""Data-quality gateway: the rules that stop a broken refresh from replacing the data layer.

Every test builds a tiny DuckDB table that satisfies one contract from `hqai_ml.ingest.quality`, breaks exactly
one rule, and asserts what the gateway does with it. No Postgres, no files from data/, nothing over a few rows.
The gateway is the guard the project promises in `docs/data.md`: implausible dates never reach Parquet, codes keep
their shape, an outcome never precedes its registration unless a flag says the source recorded it that way, and
day-hospital rows are classified rather than filtered.
"""

from __future__ import annotations

import datetime as dt
import json

import duckdb
import pytest
import yaml

from hqai_ml.ingest.config import IngestParams
from hqai_ml.ingest.quality import (
    CONTRACTS,
    QualityGateError,
    Thresholds,
    check_processed,
    gate,
    load_thresholds,
    run_gateway,
)

WINDOW_MIN = dt.date(2024, 6, 1)
WINDOW_MAX = dt.date(2026, 6, 30)


@pytest.fixture
def params() -> IngestParams:
    """The plausibility window and day-hospital code the real pipeline uses (ml/configs/ingest.yaml)."""
    return IngestParams(
        window_start=dt.date(2025, 1, 1),
        window_end=dt.date(2025, 3, 31),
        planned_dt_min=WINDOW_MIN,
        planned_dt_max=WINDOW_MAX,
        region_vote_min_share=0.8,
        fuzzy_min_score=90.0,
        fuzzy_min_sort_score=95.0,
        day_hospital_code="DH",
        day_hospital_name="Дневной стационар",
    )


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    yield connection
    connection.close()


def make_dim_profile(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.execute(
        "CREATE TABLE dim_profile (profile_code VARCHAR, profile_name VARCHAR, name_share DOUBLE, "
        "n_referrals BIGINT, is_day_hospital BOOLEAN)"
    )
    con.executemany("INSERT INTO dim_profile VALUES (?, ?, ?, ?, ?)", rows)


def make_dim_region(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.execute(
        "CREATE TABLE dim_region (region_code VARCHAR, region_name VARCHAR, vote_region_name VARCHAR, "
        "vote_share DOUBLE, vote_referrals BIGINT, runner_up_name VARCHAR, runner_up_share DOUBLE, "
        "is_ambiguous BOOLEAN, manual_override BOOLEAN)"
    )
    if rows:
        con.executemany("INSERT INTO dim_region VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def region_row(code: str, name: str = "Область") -> tuple:
    return (code, name, name, 0.9, 100, None, None, False, False)


def run(con, params, tables: list[str], *, enforce: bool = False, thresholds: Thresholds | None = None) -> dict:
    return run_gateway(con, params, thresholds or Thresholds(), enforce=enforce, tables=tables)


def check(report: dict, table: str, rule: str, column: str | None = None) -> dict:
    """The single check of that rule (and column) in the report; fails loudly when the rule did not run."""
    hits = [
        c
        for c in report["tables"][table]["checks"]
        if c["rule"] == rule and (column is None or c.get("column") == column)
    ]
    if not hits:
        ran = [c["rule"] for c in report["tables"][table]["checks"]]
        raise AssertionError(f"{table}: rule {rule!r} column {column!r} did not run; rules present: {ran}")
    assert len(hits) == 1, f"{table}: rule {rule!r} column {column!r} matched {len(hits)} checks"
    return hits[0]


class TestContractShape:
    """A contract is a promise about columns and types; a refresh that changes them must not pass silently."""

    def test_complete_table_passes(self, con, params):
        make_dim_region(con, [region_row("11"), region_row("12")])
        report = run(con, params, ["dim_region"])
        assert report["status"] == "PASS"
        assert report["tables"]["dim_region"]["rows"] == 2
        assert report["hard_violations"] == []

    def test_missing_column_fails(self, con, params):
        con.execute("CREATE TABLE dim_icd (icd10_code VARCHAR, name_share DOUBLE, n_referrals BIGINT)")
        con.execute("INSERT INTO dim_icd VALUES ('A00', 1.0, 5)")
        report = run(con, params, ["dim_icd"])
        assert report["status"] == "FAIL"
        assert check(report, "dim_icd", "required_columns")["status"] == "FAIL"
        assert any("required_columns" in violation for violation in report["hard_violations"])

    def test_wrong_type_family_fails(self, con, params):
        con.execute(
            "CREATE TABLE dim_icd (icd10_code VARCHAR, icd10_name VARCHAR, name_share VARCHAR, n_referrals BIGINT)"
        )
        con.execute("INSERT INTO dim_icd VALUES ('A00', 'Холера', 'one', 5)")
        report = run(con, params, ["dim_icd"])
        assert report["status"] == "FAIL"
        assert check(report, "dim_icd", "column_type", "name_share")["status"] == "FAIL"

    def test_unknown_table_is_rejected(self, con, params):
        with pytest.raises(ValueError, match="without a quality contract"):
            run(con, params, ["not_a_table"])


class TestCodesAndKeys:
    """Codes carry meaning downstream: a null or malformed code is a defect, not a missing value."""

    def test_null_required_code_fails(self, con, params):
        make_dim_region(con, [region_row("11"), region_row(None)])
        report = run(con, params, ["dim_region"])
        assert report["status"] == "FAIL"
        assert check(report, "dim_region", "not_null", "region_code")["count"] == 1

    def test_region_code_must_be_two_digits(self, con, params):
        make_dim_region(con, [region_row("11"), region_row("7")])
        report = run(con, params, ["dim_region"])
        assert report["status"] == "FAIL"
        malformed = check(report, "dim_region", "region_code_format", "region_code")
        assert malformed["status"] == "FAIL" and malformed["count"] == 1

    def test_duplicate_key_fails(self, con, params):
        make_dim_region(con, [region_row("11"), region_row("11", "Другая")])
        report = run(con, params, ["dim_region"])
        assert report["status"] == "FAIL"
        assert check(report, "dim_region", "unique_key")["count"] == 1

    def test_empty_table_fails(self, con, params):
        make_dim_region(con, [])
        report = run(con, params, ["dim_region"])
        assert report["status"] == "FAIL"
        assert check(report, "dim_region", "non_empty")["status"] == "FAIL"


class TestDayHospital:
    """Day-hospital rows are classified and reported, never filtered: the accepted evidence includes them."""

    def test_share_is_reported_and_rows_are_kept(self, con, params):
        make_dim_profile(
            con,
            [
                ("011", "Общие", 1.0, 10, False),
                ("021", "Терапевтические", 1.0, 10, False),
                ("DH", "Дневной стационар", 1.0, 10, True),
            ],
        )
        report = run(con, params, ["dim_profile"])
        assert report["status"] == "PASS"
        share = check(report, "dim_profile", "day_hospital_share", "profile_code")
        assert share["status"] == "INFO"
        assert share["count"] == 1
        assert share["share"] == pytest.approx(1 / 3, abs=1e-6)
        assert report["tables"]["dim_profile"]["rows"] == 3
        assert report["day_hospital_code"] == "DH"

    def test_flag_must_match_the_code(self, con, params):
        make_dim_profile(con, [("DH", "Дневной стационар", 1.0, 10, False)])
        report = run(con, params, ["dim_profile"])
        assert report["status"] == "FAIL"
        assert check(report, "dim_profile", "day_hospital_flag", "profile_code")["count"] == 1


class TestThresholds:
    """Thresholds come from ingest.yaml when it has a quality section, else from module constants."""

    def test_defaults_when_the_config_has_no_section(self, tmp_path):
        (tmp_path / "ingest.yaml").write_text("window_start: 2025-01-01\n", encoding="utf-8")
        thresholds, provenance = load_thresholds(tmp_path)
        assert thresholds.max_null_code_share == 0.0
        assert "module constants" in provenance

    def test_config_section_wins(self, tmp_path):
        (tmp_path / "ingest.yaml").write_text(
            yaml.safe_dump({"quality": {"max_out_of_window_date_share": 0.25}}), encoding="utf-8"
        )
        thresholds, provenance = load_thresholds(tmp_path)
        assert thresholds.max_out_of_window_date_share == 0.25
        assert provenance.endswith("quality")

    def test_report_records_the_window_and_thresholds(self, con, params):
        make_dim_region(con, [region_row("11")])
        report = run(con, params, ["dim_region"])
        assert report["date_window"] == {"min": WINDOW_MIN.isoformat(), "max": WINDOW_MAX.isoformat()}
        assert report["thresholds"]["max_null_code_share"] == 0.0
        assert report["mode"] == "check"


class TestGateBehaviour:
    """`gate()` is what ingest calls: it writes the report and raises before anything is written."""

    def test_raises_and_still_writes_the_report(self, con, params, tmp_path):
        make_dim_region(con, [region_row("11"), region_row(None)])
        (tmp_path / "ingest.yaml").write_text("{}\n", encoding="utf-8")
        report_path = tmp_path / "_quality_report.json"
        with pytest.raises(QualityGateError, match="data-quality gateway failed"):
            gate(con, params, tmp_path, report_path, enforce=True, tables=["dim_region"])
        written = json.loads(report_path.read_text(encoding="utf-8"))
        assert written["status"] == "FAIL"
        assert written["mode"] == "enforce"
        assert any("not_null" in violation for violation in written["hard_violations"])

    def test_passes_and_returns_the_report(self, con, params, tmp_path):
        make_dim_region(con, [region_row("11")])
        (tmp_path / "ingest.yaml").write_text("{}\n", encoding="utf-8")
        report = gate(con, params, tmp_path, tmp_path / "r.json", enforce=True, tables=["dim_region"])
        assert report["status"] == "PASS"
        assert (tmp_path / "r.json").exists()


class TestCheckProcessed:
    """The read-only mode (`ingest.py --check-quality`) opens Parquet views and never writes to the data layer."""

    def test_reads_parquet_and_reports(self, con, params, tmp_path):
        make_dim_region(con, [region_row("11"), region_row("12")])
        processed = tmp_path / "processed"
        processed.mkdir()
        con.execute(f"COPY dim_region TO '{processed / 'dim_region.parquet'}' (FORMAT parquet)")
        configs = tmp_path / "configs"
        configs.mkdir()
        (configs / "ingest.yaml").write_text("{}\n", encoding="utf-8")
        report = check_processed(processed, params, configs, None)
        assert report["status"] == "PASS"
        assert report["mode"] == "check"
        assert list(report["tables"]) == ["dim_region"]
        assert str(processed) in report["source"]
        assert sorted(p.name for p in processed.iterdir()) == ["dim_region.parquet"]

    def test_missing_tables_are_an_error(self, params, tmp_path):
        processed = tmp_path / "processed"
        processed.mkdir()
        configs = tmp_path / "configs"
        configs.mkdir()
        (configs / "ingest.yaml").write_text("{}\n", encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="no contracted Parquet tables"):
            check_processed(processed, params, configs, None)


def test_every_contract_names_its_key_among_its_columns():
    """A contract whose key is not one of its own columns could never be checked."""
    for table, contract in CONTRACTS.items():
        missing = [column for column in contract.key if column not in contract.columns]
        assert not missing, f"{table}: key columns {missing} are not declared in the contract"
        unknown_not_null = [column for column in contract.not_null if column not in contract.columns]
        assert not unknown_not_null, f"{table}: not_null columns {unknown_not_null} are not declared"
