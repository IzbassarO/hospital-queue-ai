"""Locate raw CSV parts, validate them, and stage them into DuckDB as VARCHAR tables.

data/raw is read-only: files are only opened for reading.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

EXPECTED_HEADERS = {
    1: [
        "hospitalization_code",
        "referring_mo",
        "hospital_mo",
        "icd10_ref_diag_code",
        "diagnosis_name",
        "bed_profile",
        "registration_dt",
        "planned_dt",
        "polyclinic_dt",
        "hospitalization_dt",
        "refusal_dt",
        "territorial_type",
        "referral_purpose",
        "finance_source",
        "sdu_load_date",
    ],
    2: [
        "region_origin_code",
        "mo_destination_code",
        "profile_code",
        "patient_seq_no",
        "icd10_ref_diag_code",
        "diagnosis_name",
        "operation_code",
        "operation_name",
        "registration_dt",
        "planned_dt",
        "sdu_load_date",
    ],
    3: [
        "region_in",
        "org_in",
        "resident",
        "insured",
        "benefit_cat",
        "refuse_dt",
        "attach_region",
        "attach_org",
        "icd10",
        "icd_name",
        "amount",
        "finance_src",
        "sdu_load_date",
    ],
    4: [
        "medicine_organization",
        "discharged_total",
        "discharged_children",
        "treated_budget",
        "treated_paid",
        "discharged_within_day",
        "deaths_total",
        "bed_days",
        "amount_to_pay",
        "sdu_load_date",
    ],
}
_PART = re.compile(r"Часть\s+(\d+)\s+из\s+(\d+)", re.IGNORECASE)


@dataclass
class SourceFiles:
    dataset: int
    valid: list[Path] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # {"file", "reason"}


def _check_part(path: Path, expected: list[str]) -> str | None:
    """Return a reason why the file is unusable, or None if it looks like a valid CSV part."""
    if path.stat().st_size == 0:
        return "empty file"
    with open(path, "rb") as f:
        head = f.read(8192)
    text = head.decode("utf-8-sig", errors="replace").lstrip()
    if text.startswith("<?xml") or text.startswith("<Error"):
        return "not a CSV (XML error response of a failed download)"
    header = text.splitlines()[0].strip().split(",") if text else []
    if header != expected:
        return f"unexpected header: {','.join(header)[:120]}"
    with open(path, "rb") as f:
        f.seek(max(0, path.stat().st_size - 2))
        if not f.read().endswith(b"\n"):
            return "file does not end with a newline (truncated download?)"
    return None


def find_sources(raw_dir: Path, dataset: int) -> SourceFiles:
    folder = next((p for p in raw_dir.iterdir() if p.is_dir() and re.match(rf"^{dataset}\b", p.name)), None)
    result = SourceFiles(dataset)
    if folder is None:
        return result
    for path in sorted(folder.glob("*.csv")):
        reason = _check_part(path, EXPECTED_HEADERS[dataset])
        if reason:
            result.skipped.append({"file": path.name, "reason": reason})
        else:
            result.valid.append(path)
    return result


def part_number(file_name: str) -> int:
    m = _PART.search(file_name)
    return int(m.group(1)) if m else 1


def stage_csv(con: duckdb.DuckDBPyConnection, table: str, sources: SourceFiles) -> int:
    """CREATE TABLE <table> with all columns VARCHAR plus `source_file`."""
    if not sources.valid:
        raise FileNotFoundError(f"dataset {sources.dataset}: no valid CSV files ({sources.skipped})")
    paths = "[" + ", ".join("'" + str(p).replace("'", "''") + "'" for p in sources.valid) + "]"
    con.execute(
        f"""CREATE OR REPLACE TABLE {table} AS
            SELECT * EXCLUDE (filename), regexp_extract(filename, '[^/]+$') AS source_file
            FROM read_csv({paths}, header=true, delim=',', quote='"', escape='"',
                          all_varchar=true, filename=true)"""
    )
    return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
