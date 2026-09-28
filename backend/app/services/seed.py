"""Demo seed loader: seed/ (built by tools/seed_bundle.py) into a migrated database, then the six publications.

Why it lives in the backend: a fresh clone has neither the 16 GB of MoH data nor the hours of pipelines that produce
the serving tables and the accepted evidence, yet `make demo` must bring the product up complete with Docker alone.
The seed is therefore loaded by the same image that serves the API, inside the compose network, with no ML dependency.

Safety: every file is checked against manifest.json before anything is written; tables are COPYed in foreign-key
order in one transaction and their row counts must match the manifest; a database that already holds the seed (same
row counts in every seeded table and the seed's mart_build_info.built_at, a cheap content probe) is left alone (the
publications are only re-activated); any other non-empty seeded table stops the load unless
replace=True, which truncates the seeded data tables (plus fact_admission_refusal, which references them) and never
api_keys, access_log or the decision tables. The bundles go through model_assurance.publish,
operational_intelligence.publish, review_evidence.publish, waiting_list.publish, referral_estimates.publish and
verification_worklist.publish, so the identity and provenance checks are those of the administrative publish
commands, and a bundle that is already published is activated, not duplicated.
"""

import csv
import datetime as dt
import gzip
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import (
    model_assurance,
    operational_intelligence,
    referral_estimates,
    review_evidence,
    verification_worklist,
    waiting_list,
)

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
# referenced by the seeded dictionaries, not seeded itself: a --replace truncate must include it
REPLACE_ALSO = ("fact_admission_refusal",)
SERIAL_COLUMNS = (("fact_referral", "referral_id"), ("pred_referral", "referral_id"))
# operational intelligence verifies the assurance snapshot, review evidence verifies both; the waiting list
# stands alone (measured data, no model provenance to verify), and the per-referral estimates go last because
# they are read beside a waiting-list row
BUNDLE_ORDER = (
    "model_assurance",
    "operational_intelligence",
    "review_evidence",
    "waiting_list",
    "referral_estimates",
    "verification_worklist",
)
# the one-row table whose build timestamp identifies a mart build: equal counts alone do not prove the same content
BUILD_INFO_TABLE = "mart_build_info"


class SeedError(Exception):
    """The seed directory is inconsistent or the database state forbids loading; the CLI maps it to exit code 2."""


@dataclass(frozen=True)
class TableLoad:
    table: str
    rows: int


@dataclass(frozen=True)
class BundlePublication:
    kind: str
    publication_id: str
    identity_sha256: str
    created: bool


@dataclass(frozen=True)
class SeedSummary:
    tables: list[TableLoad]
    tables_skipped: bool
    publications: list[BundlePublication]


def read_manifest(seed_dir: Path) -> dict:
    path = seed_dir / "manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SeedError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SeedError(f"{path}: invalid JSON: {exc}") from exc
    for key in ("tables", "bundles"):
        if not isinstance(manifest.get(key), list) or not manifest[key]:
            raise SeedError(f"{path}: {key!r} missing or empty")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def verify_files(seed_dir: Path, manifest: dict) -> None:
    for entry in [*manifest["tables"], *manifest["bundles"]]:
        path = seed_dir / entry["file"]
        if not path.is_file():
            raise SeedError(f"{entry['file']}: listed in manifest.json but missing")
        if path.stat().st_size != entry["bytes"] or _sha256(path) != entry["sha256"]:
            raise SeedError(f"{entry['file']}: size or SHA-256 differs from manifest.json")


def _ident(name: str) -> str:
    if not IDENTIFIER.match(name):
        raise SeedError(f"{name!r} is not a plain SQL identifier")
    return name


def _count(session: Session, table: str) -> int:
    return session.execute(text(f"SELECT count(*) FROM {_ident(table)}")).scalar_one()


def _copy_table(session: Session, table: str, path: Path) -> None:
    driver_connection = session.connection().connection.driver_connection
    with gzip.open(path, "rb") as fh:
        header = fh.readline().decode("utf-8").strip()
        columns = ", ".join(_ident(column) for column in header.split(","))
        with (
            driver_connection.cursor() as cursor,
            cursor.copy(f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)") as copy,
        ):
            while chunk := fh.read(1 << 20):
                copy.write(chunk)


def _seed_built_at(seed_dir: Path, manifest: dict) -> dt.datetime | None:
    """built_at of the seeded mart_build_info row, or None when the seed does not ship that table."""
    entry = next((entry for entry in manifest["tables"] if entry["table"] == BUILD_INFO_TABLE), None)
    if entry is None:
        return None
    with gzip.open(seed_dir / entry["file"], "rt", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        row = next(reader, None)
    if row is None or "built_at" not in header:
        return None
    return dt.datetime.fromisoformat(row[header.index("built_at")])


def _database_built_at(session: Session) -> dt.datetime | None:
    return session.execute(text(f"SELECT max(built_at) FROM {BUILD_INFO_TABLE}")).scalar_one()


def holds_more_than_seed(counts: dict[str, int], entries: list[dict]) -> bool:
    """True when the database already carries a superset of the seed, so the tables must be left alone.

    A database built by the full pipeline holds more than the seed does: the seed's referral-level tables are a
    two-region slice of the country. Replacing that with less data would be wrong, and it needs no seeding at all,
    so `make demo` works on a machine that has already run `make ingest predict marts` and only the publications
    are loaded. A table with fewer rows than the seed means partial or damaged data, which is not this case.
    """
    richer = any(counts[entry["table"]] > entry["rows"] for entry in entries)
    poorer = any(0 < counts[entry["table"]] < entry["rows"] for entry in entries)
    return richer and not poorer


def load_tables(session: Session, seed_dir: Path, manifest: dict, replace: bool) -> tuple[list[TableLoad], bool]:
    """COPY every table of the manifest in one transaction; returns the loads and whether they were skipped."""
    entries = manifest["tables"]
    tables = [_ident(entry["table"]) for entry in entries]
    with session.begin():
        counts = {table: _count(session, table) for table in tables}
        same_counts = all(counts[entry["table"]] == entry["rows"] for entry in entries)
        seed_built_at = _seed_built_at(seed_dir, manifest) if same_counts and not replace else None
        same_build = seed_built_at is None or _database_built_at(session) == seed_built_at
        if same_counts and same_build and not replace:
            return [TableLoad(entry["table"], entry["rows"]) for entry in entries], True
        occupied = [table for table in tables if counts[table]]
        if occupied and not replace:
            if holds_more_than_seed(counts, entries):
                return [TableLoad(entry["table"], counts[entry["table"]]) for entry in entries], True
            differing = (
                ", ".join(
                    f"{entry['table']} ({counts[entry['table']]:,} rows, seed {entry['rows']:,})"
                    for entry in entries
                    if counts[entry["table"]] != entry["rows"]
                )
                or f"{BUILD_INFO_TABLE}.built_at differs from the seed ({seed_built_at:%Y-%m-%d %H:%M:%S})"
            )
            raise SeedError(
                f"database already holds data that is not this seed: {differing}; "
                "pass --replace to truncate the seeded data tables first (keys, access log and decisions are kept)"
            )
        if occupied:
            session.execute(text(f"TRUNCATE {', '.join([*tables, *REPLACE_ALSO])}"))
        loaded = []
        for entry in entries:
            table = _ident(entry["table"])
            _copy_table(session, table, seed_dir / entry["file"])
            rows = _count(session, table)
            if rows != entry["rows"]:
                raise SeedError(f"{table}: loaded {rows} rows, manifest.json says {entry['rows']}")
            loaded.append(TableLoad(table, rows))
        for table, column in SERIAL_COLUMNS:
            session.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                    f"coalesce((SELECT max({column}) FROM {table}), 1))"
                )
            )
    return loaded, False


def _bundle_bytes(path: Path, expected_sha256: str) -> bytes:
    data = path.read_bytes()
    if path.suffix == ".gz":
        data = gzip.decompress(data)
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise SeedError(f"{path.name}: decompressed content differs from raw_sha256 in manifest.json")
    return data


def publish_bundles(session: Session, seed_dir: Path, manifest: dict) -> list[BundlePublication]:
    by_kind = {entry["kind"]: entry for entry in manifest["bundles"]}
    missing = [kind for kind in BUNDLE_ORDER if kind not in by_kind]
    if missing:
        raise SeedError(f"manifest.json lacks bundle(s): {', '.join(missing)}")
    publications = []
    for kind in BUNDLE_ORDER:
        entry = by_kind[kind]
        raw = _bundle_bytes(seed_dir / entry["file"], entry["raw_sha256"])
        if kind == "model_assurance":
            result = model_assurance.publish(session, model_assurance.parse_assurance_bundle(raw))
            published_id, identity = result.assurance_id, result.assurance_identity_sha256
        elif kind == "operational_intelligence":
            result = operational_intelligence.publish(session, operational_intelligence.parse_bundle(raw))
            published_id, identity = result.publication_id, result.publication_identity_sha256
        elif kind == "waiting_list":
            result = waiting_list.publish(session, waiting_list.parse_bundle(raw))
            published_id, identity = result.publication_id, result.publication_identity_sha256
        elif kind == "referral_estimates":
            result = referral_estimates.publish(session, referral_estimates.parse_bundle(raw))
            published_id, identity = result.publication_id, result.publication_identity_sha256
        elif kind == "verification_worklist":
            result = verification_worklist.publish(session, verification_worklist.parse_bundle(raw))
            published_id, identity = result.publication_id, result.publication_identity_sha256
        else:
            result = review_evidence.publish(session, review_evidence.parse_bundle(raw))
            published_id, identity = result.publication_id, result.publication_identity_sha256
        publication = BundlePublication(kind, published_id, identity, result.created)
        if publication.identity_sha256 != entry["identity_sha256"]:
            raise SeedError(
                f"{kind}: published identity {publication.identity_sha256} differs from manifest.json "
                f"({entry['identity_sha256']})"
            )
        publications.append(publication)
    return publications


def load(session: Session, seed_dir: Path, replace: bool = False) -> SeedSummary:
    """Verify, load the tables, publish the bundles. Raises SeedError, ValidationError or ConflictError."""
    manifest = read_manifest(seed_dir)
    verify_files(seed_dir, manifest)
    tables, skipped = load_tables(session, seed_dir, manifest, replace)
    publications = publish_bundles(session, seed_dir, manifest)
    return SeedSummary(tables=tables, tables_skipped=skipped, publications=publications)


def format_summary(summary: SeedSummary, database: str) -> str:
    total = sum(load.rows for load in summary.tables)
    state = "already present, left unchanged" if summary.tables_skipped else "loaded"
    lines = [f"seed -> database {database!r}: {len(summary.tables)} tables, {total:,} rows {state}"]
    lines += [f"  {load.table:<30} {load.rows:>9,}" for load in summary.tables]
    for publication in summary.publications:
        verb = "published" if publication.created else "already published; activated"
        lines.append(f"  {publication.kind:<26} {publication.publication_id}  {verb}")
        lines.append(f"  {'':<26} identity {publication.identity_sha256}")
    return "\n".join(lines)
