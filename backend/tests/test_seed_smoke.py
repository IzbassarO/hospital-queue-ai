"""Smoke test of the committed demo seed after `python -m app.cli load-seed --dir ../seed` (CI job demo-seed).

Runs only with HQAI_SEED_SMOKE=1: it asserts the seed's row counts and publication identities, which do not hold on a
database with the full data (`make test`). The API keys come from conftest (admin.create_key) and are removed at the
end like in the other suites.
"""

import json
import os
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.db.session import SessionLocal
from conftest import API

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(os.environ.get("HQAI_SEED_SMOKE") != "1", reason="set HQAI_SEED_SMOKE=1 after load-seed"),
]

SEED_DIR = Path(__file__).resolve().parents[2] / "seed"
ASSURANCE_IDENTITY = "f504defefdd87bcbb01c670b68469ba4c0e016be7f40ca89452baf69b73f39f5"
OPERATIONAL_IDENTITY = "43da33ece7231a70348043c2bb8ec4b63161f94ed67dfe96e3c36de69c425cfd"
REVIEW_IDENTITY = "e07be2f158c69ed50c9da2286a9459424947d02266e5094c5627b7648be33c22"
WAITING_IDENTITY = "1c4fceb133538ae7ed08c11a885bcf68c001a66aef0840b7ec572a453a12b188"
REFERRAL_ESTIMATES_IDENTITY = "8c83c771af730e6edd793da913813ff0c503cff09d6ca863ce07cfb71b5d1b17"
VERIFICATION_WORKLIST_IDENTITY = "e9d93b009064bf8b2eb88192e2b846052550a835a44732ec7ce25cc73eb59e1f"
# hindsight lives in its own disclosed fields; an origin-time row of a model publication never carries it
HINDSIGHT_TOKENS = ("observed", "outcome", "status", "hindsight", "event_date")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((SEED_DIR / "manifest.json").read_text(encoding="utf-8"))


def rows(manifest: dict, table: str) -> int:
    return next(entry["rows"] for entry in manifest["tables"] if entry["table"] == table)


def bundle(manifest: dict, kind: str) -> dict:
    return next(entry for entry in manifest["bundles"] if entry["kind"] == kind)


async def get_json(client: httpx.AsyncClient, path: str, **params):
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
    return response.json()


def test_row_counts_match_manifest(manifest):
    with SessionLocal() as session:
        for entry in manifest["tables"]:
            count = session.execute(text(f"SELECT count(*) FROM {entry['table']}")).scalar_one()
            assert count == entry["rows"], f"{entry['table']}: {count} rows, manifest says {entry['rows']}"


def test_manifest_identities(manifest):
    """Exactly these six publications: a missing, an extra or a changed one all fail."""
    kinds = [entry["kind"] for entry in manifest["bundles"]]
    assert len(kinds) == len(set(kinds)), f"duplicate bundle kinds: {kinds}"
    identities = {entry["kind"]: entry["identity_sha256"] for entry in manifest["bundles"]}
    assert identities == {
        "model_assurance": ASSURANCE_IDENTITY,
        "operational_intelligence": OPERATIONAL_IDENTITY,
        "review_evidence": REVIEW_IDENTITY,
        "waiting_list": WAITING_IDENTITY,
        "referral_estimates": REFERRAL_ESTIMATES_IDENTITY,
        "verification_worklist": VERIFICATION_WORKLIST_IDENTITY,
    }


async def test_operational_overview(client, manifest):
    body = await get_json(client, "/operational-intelligence/overview")
    snapshot = body["snapshot"]
    counts = bundle(manifest, "operational_intelligence")["counts"]
    assert snapshot["publication_identity_sha256"] == OPERATIONAL_IDENTITY
    assert snapshot["assurance_identity_sha256"] == ASSURANCE_IDENTITY
    assert snapshot["forecast_count"] == counts["forecast_count"]
    assert snapshot["signal_count"] == counts["signal_count"]
    assert len(body["regions"]) == rows(manifest, "dim_region")


async def test_high_signals(client):
    body = await get_json(client, "/operational-intelligence/signals", severity="HIGH", limit=5)
    assert body["items"] and len(body["items"]) <= 5
    assert body["total"] >= len(body["items"])
    for item in body["items"]:
        assert item["severity"] == "HIGH"
        assert item["publication_identity_sha256"] == OPERATIONAL_IDENTITY


async def test_model_assurance(client, manifest):
    body = await get_json(client, "/model-assurance")
    assert body["assurance_identity_sha256"] == ASSURANCE_IDENTITY
    assert body["assurance_id"] == bundle(manifest, "model_assurance")["publication_id"]


async def test_review_overview(client, manifest):
    body = await get_json(client, "/review-evidence/overview")
    snapshot = body["snapshot"]
    assert snapshot["publication_identity_sha256"] == REVIEW_IDENTITY
    assert snapshot["operational_publication_identity_sha256"] == OPERATIONAL_IDENTITY
    assert snapshot["assurance_identity_sha256"] == ASSURANCE_IDENTITY
    assert len(body["scenarios"]) == bundle(manifest, "review_evidence")["counts"]["scenario_count"]


async def test_overview_and_dictionaries(client, manifest):
    overview = await get_json(client, "/overview")
    assert len(overview["regions"]) == rows(manifest, "dim_region")
    dictionaries = await get_json(client, "/dictionaries")
    assert len(dictionaries["regions"]) == rows(manifest, "dim_region")
    assert len(dictionaries["profiles"]) == rows(manifest, "dim_profile")


async def all_hospitals(client: httpx.AsyncClient) -> list[dict]:
    """Every hospital of the publication. The page cap is 500 and the seed holds 640, so this must page."""
    items: list[dict] = []
    while True:
        page = await get_json(client, "/waiting-list/hospitals", limit=500, offset=len(items))
        items += page["items"]
        if not page["items"] or len(items) >= page["total"]:
            return items


async def test_waiting_list_is_national_in_the_seed(client, manifest):
    """The referral tables are a two-region slice, but the waiting list answers for the whole country."""
    counts = bundle(manifest, "waiting_list")["counts"]
    first = await get_json(client, "/waiting-list/hospitals", limit=500)
    assert first["total"] == counts["hospital_count"]
    items = await all_hospitals(client)
    assert len(items) == counts["hospital_count"]
    assert {row["publication_identity_sha256"] for row in items} == {WAITING_IDENTITY}
    assert len({row["region_code"] for row in items}) == rows(manifest, "dim_region")
    assert sum(row["waiting_count"] for row in items) == counts["waiting_count"]


async def test_waiting_list_referrals_carry_no_model_value(client):
    hospitals = await get_json(client, "/waiting-list/hospitals", limit=1)
    org = hospitals["items"][0]["org_code"]
    body = await get_json(client, f"/waiting-list/hospitals/{org}/referrals", limit=25)
    assert body["total"] == hospitals["items"][0]["waiting_count"]
    forbidden = ("pred", "probability", "severity", "forecast", "score", "risk", "calibration")
    for item in body["items"]:
        assert item["registration_date"] <= item["origin"]
        assert item["profile_code"] != "DH"
        assert item["observed_after_origin"]["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
        assert not [key for key in item if any(token in key for token in forbidden)]


async def busiest_hospital(client: httpx.AsyncClient) -> dict:
    return (await get_json(client, "/waiting-list/hospitals", limit=1))["items"][0]


async def test_referral_estimates_publication(client, manifest):
    body = await get_json(client, "/referral-estimates/publication")
    entry = bundle(manifest, "referral_estimates")
    assert body["publication_identity_sha256"] == REFERRAL_ESTIMATES_IDENTITY
    assert body["publication_id"] == entry["publication_id"]
    assert body["referral_count"] == entry["counts"]["referral_count"]
    # it stands at the waiting list's origin, so the queue screen can show both on one row
    assert body["matches_waiting_list"] is True


async def test_referral_estimates_ride_on_the_queue_with_their_own_lineage(client):
    publication = await get_json(client, "/referral-estimates/publication")
    hospital = await busiest_hospital(client)
    body = await get_json(client, f"/referral-estimates/hospitals/{hospital['org_code']}/referrals", limit=25)
    assert body["total"] == hospital["waiting_count"]
    estimates = [item["estimate"] for item in body["items"] if item["estimate"] is not None]
    assert estimates, "no served queue row carries an origin-time estimate"
    for estimate in estimates:
        assert estimate["publication_identity_sha256"] == REFERRAL_ESTIMATES_IDENTITY
        assert estimate["publication_id"] == publication["publication_id"]
        assert estimate["origin"] == publication["origin"]
        assert not [key for key in estimate if any(token in key for token in HINDSIGHT_TOKENS)]


async def test_verification_worklist_publication(client, manifest):
    body = await get_json(client, "/verification-worklist/publication")
    assert body["publication_identity_sha256"] == VERIFICATION_WORKLIST_IDENTITY
    assert body["publication_id"] == bundle(manifest, "verification_worklist")["publication_id"]
    assert body["schema_version"] == "verification_worklist_v2"
    assert body["source_publication"]["publication_id"] == "ghost-queue-2025-03-17-v2"
    assert body["source_publication"]["schema_version"] == 2
    assert body["decision_owner"] == "SPECIALIST_DECIDES"
    assert body["legacy_rule"]["role"] == "AUDITED_REFERENCE_ONLY"
    # the list orders the whole measured queue and subtracts nothing from it
    waiting = bundle(manifest, "waiting_list")["counts"]["waiting_count"]
    assert body["counts"] == {"formal_queue_count": waiting, "ranked_count": waiting}


async def test_verification_worklist_rows_are_origin_time_and_leave_the_queue_whole(client):
    hospital = await busiest_hospital(client)
    body = await get_json(client, f"/verification-worklist/hospitals/{hospital['org_code']}", limit=25)
    assert body["formal_queue_count"] == hospital["waiting_count"]
    assert body["total"] == hospital["waiting_count"]
    assert body["items"]
    for item in body["items"]:
        assert item["publication_identity_sha256"] == VERIFICATION_WORKLIST_IDENTITY
        assert item["decision_owner"] == "SPECIALIST_DECIDES"
        assert not [key for key in item if any(token in key for token in HINDSIGHT_TOKENS)]
    # reading the worklist did not touch the measured queue
    assert (await busiest_hospital(client))["waiting_count"] == hospital["waiting_count"]


async def test_every_seed_publication_is_in_the_transparency_ledger(client, manifest):
    """Loading the seed publishes all six bundles through the ordinary publish path, so each one is chained
    (published, then activated) with the manifest's identity, and the whole ledger verifies against the rows."""
    for entry in manifest["bundles"]:
        subject = f"publication:{entry['kind']}:{entry['publication_id']}"
        found = await get_json(client, "/transparency/lookup", subject=subject)
        published = [e for e in found if e["event_type"] == "publication.published"]
        assert len(published) == 1, subject
        assert published[0]["payload"]["identity_sha256"] == entry["identity_sha256"]
        assert "publication.activated" in {e["event_type"] for e in found}, subject
    report = await get_json(client, "/transparency/verify")
    assert report["status"] == "OK", report["issues"]
    assert report["covered_publications"] >= len(manifest["bundles"])
