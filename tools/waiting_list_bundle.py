#!/usr/bin/env python3
"""Offline export of the REAL waiting list at one origin; never imported by the API.

  make waiting-list-bundle            -> artifacts/waiting_list/<publication-id>/waiting_list.json

No model runs here and none may: the export reads `fact_referral` and writes the queue exactly as the Ministry of
Health data recorded it. Two things go into every row — what was true at the end of the origin day (hospital,
region, profile, registration date, days already waited) and, in a separate `observed_after_origin` object, what
the data later recorded as the outcome. The second is hindsight; it is marked as such on every row and exists to
check an origin-time claim afterwards, never to feed one.

Cohort: registered on or before the origin, with no terminal event by the end of the origin day
(`resolution_date IS NULL OR resolution_date > origin`), excluding day-hospital profiles (CLAUDE.md §3).

The queue is a lower bound: the source data begins on 2025-01-01, so anyone registered in 2024 and still waiting
is not in it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.session import SessionLocal  # noqa: E402
from app.schemas.waiting_list import (  # noqa: E402
    HINDSIGHT_DISCLOSURE,
    SupportThresholds,
    WaitingListBundle,
)
from app.services.waiting_list import identity_of, parse_bundle  # noqa: E402

ORIGIN = "2025-03-17"
PUBLICATION = "waiting-list-origin-2025-03-17-v1"
OUTPUT_DIR = "artifacts/waiting_list"
EXCLUDED_PROFILE_CODES = ("DH",)
# a per-hospital view needs enough rows to mean anything; the numbers are published, so a reader can check them
SUFFICIENT_MIN = 50
LIMITED_MIN = 20

COHORT_SQL = """
    SELECT referral_id, hospitalization_code, is_dup_code, org_code, hospital_region_code,
           region_code AS patient_region_code, profile_code, registration_date, resolution_date, outcome
    FROM fact_referral
    WHERE registration_date <= :origin
      AND (resolution_date IS NULL OR resolution_date > :origin)
      AND profile_code <> ALL(:excluded)
    ORDER BY referral_id
"""
SOURCE_BOUNDS_SQL = """
    SELECT min(registration_date) AS registration_floor,
           greatest(max(hospitalization_date), max(refusal_date)) AS observed_through
    FROM fact_referral
"""

LIMITATIONS = [
    "Измеренная очередь, не прогноз: публикация не содержит ни одной модельной величины.",
    "Источник начинается 01.01.2025, поэтому очередь на 17.03.2025 — нижняя оценка: направления, "
    "зарегистрированные в 2024 году и всё ещё ожидающие, в данных отсутствуют.",
    "Профили дневного стационара (DH) исключены из когорты.",
    "observed_after_origin — это ретроспектива (hindsight). Эти значения не были известны на дату отсечения "
    "и не должны попадать ни в один прогноз, рейтинг или порог.",
    "hospitalization_code не уникален в источнике; ключом строки служит referral_id, "
    "а совпадения кода помечены полем is_duplicate_code.",
]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def head_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"cannot read the current commit (pass --source-code-commit): {exc}") from exc
    return result.stdout.strip()


def observation(origin: dt.date, resolution_date: dt.date | None, outcome: str) -> dict:
    """The hindsight field of one row, marked on the row itself."""
    if resolution_date is None:
        return {"disclosure": HINDSIGHT_DISCLOSURE, "status": "STILL_WAITING_AT_CUTOFF"}
    return {
        "disclosure": HINDSIGHT_DISCLOSURE,
        "status": "ADMITTED" if outcome == "hospitalized" else "REFUSED",
        "event_date": resolution_date.isoformat(),
        "days_from_origin": (resolution_date - origin).days,
    }


def referral_rows(rows, origin: dt.date) -> list[dict]:
    return [
        {
            "referral_id": row.referral_id,
            "hospitalization_code": row.hospitalization_code,
            "is_duplicate_code": bool(row.is_dup_code),
            "org_code": row.org_code,
            "region_code": row.hospital_region_code,
            "patient_region_code": row.patient_region_code,
            "profile_code": row.profile_code,
            "registration_date": row.registration_date.isoformat(),
            "days_waited_at_origin": (origin - row.registration_date).days,
            "observed_after_origin": observation(origin, row.resolution_date, row.outcome),
        }
        for row in rows
    ]


def hospital_rows(referrals: list[dict], thresholds: SupportThresholds) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in referrals:
        grouped.setdefault(row["org_code"], []).append(row)
    hospitals = []
    for org_code, rows in grouped.items():
        waits = [row["days_waited_at_origin"] for row in rows]
        hospitals.append(
            {
                "org_code": org_code,
                "region_code": rows[0]["region_code"],
                "waiting_count": len(rows),
                "profile_count": len({row["profile_code"] for row in rows}),
                "median_days_waited": float(statistics.median(waits)),
                "max_days_waited": max(waits),
                "support_class": thresholds.classify(len(rows)),
            }
        )
    hospitals.sort(key=lambda row: (-row["waiting_count"], row["org_code"]))
    return hospitals


def build(origin: dt.date, publication_id: str, source_code_commit: str) -> tuple[dict, dict]:
    thresholds = SupportThresholds(sufficient_min=SUFFICIENT_MIN, limited_min=LIMITED_MIN)
    with SessionLocal() as session:
        bounds = session.execute(text(SOURCE_BOUNDS_SQL)).one()
        rows = session.execute(text(COHORT_SQL), {"origin": origin, "excluded": list(EXCLUDED_PROFILE_CODES)}).all()
    if not rows:
        raise SystemExit(f"no referral was waiting at {origin}: refusing to publish an empty waiting list")

    referrals = referral_rows(rows, origin)
    hospitals = hospital_rows(referrals, thresholds)
    payload = {
        "schema_version": "waiting_list_v1",
        "contract_version": "1.0.0",
        "publication_id": publication_id,
        "publication_identity_sha256": "0" * 64,
        "source_code_commit": source_code_commit,
        "origin": origin.isoformat(),
        "outcome_cutoff": "2026-05-13T00:00:00",
        "observed_through": bounds.observed_through.isoformat(),
        "cohort": {
            "waiting_rule": ("registration_date <= origin AND (resolution_date IS NULL OR resolution_date > origin)"),
            "excluded_profile_codes": list(EXCLUDED_PROFILE_CODES),
            "excluded_profile_reason": "дневной стационар не занимает койку плановой госпитализации (CLAUDE.md §3)",
            "registration_floor": bounds.registration_floor.isoformat(),
            "lower_bound_note": ("источник начинается с registration_floor, поэтому очередь — нижняя оценка"),
        },
        "support_thresholds": thresholds.model_dump(mode="json"),
        "carries_model_output": False,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "limitations": LIMITATIONS,
        "hospitals": hospitals,
        "referrals": referrals,
    }
    bundle = WaitingListBundle.model_validate(payload)
    payload = bundle.model_dump(mode="json")
    payload["publication_identity_sha256"] = identity_of(bundle)

    counts: dict[str, int] = {}
    for row in referrals:
        counts[row["observed_after_origin"]["status"]] = counts.get(row["observed_after_origin"]["status"], 0) + 1
    report = {
        "publication_id": publication_id,
        "origin": origin.isoformat(),
        "waiting_count": len(referrals),
        "hospital_count": len(hospitals),
        "support": {
            name: sum(1 for row in hospitals if row["support_class"] == name)
            for name in ("SUFFICIENT", "LIMITED", "SPARSE")
        },
        "observed_after_origin": counts,
        "regions": len({row["region_code"] for row in referrals}),
        "profiles": len({row["profile_code"] for row in referrals}),
    }
    return payload, report


def write_outputs(output: Path, files: list[tuple[str, dict]]) -> None:
    """Immutable outputs: an existing file must already hold exactly these bytes."""
    output.mkdir(parents=True, exist_ok=True)
    for name, value in files:
        path = output / name
        data = canonical(value) + b"\n"
        if path.exists():
            if path.read_bytes() != data:
                raise SystemExit(f"immutable output already exists with different content: {name}")
        else:
            temporary = path.with_suffix(".json.partial")
            temporary.write_bytes(data)
            temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root holding artifacts/")
    parser.add_argument("--origin", default=ORIGIN, help=f"origin day YYYY-MM-DD (default {ORIGIN})")
    parser.add_argument("--publication-id", default=PUBLICATION, help=f"publication id (default {PUBLICATION})")
    parser.add_argument("--source-code-commit", default=None, help="commit of the producing code (default: HEAD)")
    parser.add_argument("--out", type=Path, help=f"output directory (default {OUTPUT_DIR}/<publication-id>)")
    args = parser.parse_args()

    origin = dt.date.fromisoformat(args.origin)
    commit = args.source_code_commit or head_commit(args.root)
    payload, report = build(origin, args.publication_id, commit)
    output = args.out or args.root / OUTPUT_DIR / args.publication_id
    write_outputs(output, [("waiting_list.json", payload), ("build-report.json", report)])
    # the bytes that were written must publish: parse them back through the same path the API uses
    parsed = parse_bundle((output / "waiting_list.json").read_bytes())
    print(
        json.dumps(
            {
                "output": str(output),
                **report,
                "identity": parsed.bundle.publication_identity_sha256,
                "bundle_sha256": parsed.bundle_sha256,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
