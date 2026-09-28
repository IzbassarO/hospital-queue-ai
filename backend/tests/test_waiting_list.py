"""Waiting-list endpoints against the running database (the publication must be loaded: `make seed-load`).

The endpoints serve measured data only. These tests hold the contract that matters at the edge: viewer role is
enough, the cohort never shows a referral registered after the origin, sorting is by days waited, and the
hindsight field arrives marked and self-consistent.
"""

import datetime as dt

import httpx
import pytest

from tests.conftest import API, auth

ENDPOINT = f"{API}/waiting-list/hospitals"


@pytest.fixture(scope="module")
async def publication(client: httpx.AsyncClient) -> dict:
    response = await client.get(ENDPOINT, params={"limit": 1})
    if response.status_code == 404:
        pytest.skip("no waiting-list publication is active (run `make waiting-list-publish` or `make seed-load`)")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"], "the publication has no hospitals"
    return body


@pytest.fixture(scope="module")
async def busiest(publication: dict) -> dict:
    return publication["items"][0]


# ------------------------------------------------------------------------------------- access control


@pytest.mark.anyio
async def test_both_endpoints_require_a_key(anon_client: httpx.AsyncClient, busiest: dict) -> None:
    assert (await anon_client.get(ENDPOINT)).status_code == 401
    assert (await anon_client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals")).status_code == 401


@pytest.mark.anyio
async def test_viewer_role_is_enough(anon_client: httpx.AsyncClient, api_keys: dict[str, str], busiest: dict) -> None:
    headers = auth(api_keys["viewer"])
    assert (await anon_client.get(ENDPOINT, headers=headers)).status_code == 200
    referrals = await anon_client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals", headers=headers)
    assert referrals.status_code == 200


# ------------------------------------------------------------------------------------- hospitals list


@pytest.mark.anyio
async def test_hospitals_are_ordered_by_queue_size_and_carry_the_publication(publication: dict) -> None:
    row = publication["items"][0]
    assert publication["total"] >= 1
    assert row["waiting_count"] >= 1
    assert row["org_name"] and row["region_name"]
    assert len(row["publication_identity_sha256"]) == 64
    assert dt.date.fromisoformat(row["origin"])


@pytest.mark.anyio
async def test_hospitals_page_is_sorted_descending(client: httpx.AsyncClient) -> None:
    body = (await client.get(ENDPOINT, params={"limit": 50})).json()
    counts = [row["waiting_count"] for row in body["items"]]
    assert counts == sorted(counts, reverse=True)


@pytest.mark.anyio
async def test_support_filter_matches_the_published_thresholds(client: httpx.AsyncClient) -> None:
    sufficient = (await client.get(ENDPOINT, params={"support": "SUFFICIENT", "limit": 500})).json()
    assert all(row["support_class"] == "SUFFICIENT" for row in sufficient["items"])
    assert all(row["waiting_count"] >= 50 for row in sufficient["items"])
    by_min = (await client.get(ENDPOINT, params={"min_waiting": 50, "limit": 1})).json()
    assert by_min["total"] == sufficient["total"]


@pytest.mark.anyio
async def test_sparse_hospitals_are_flagged_rather_than_hidden(client: httpx.AsyncClient) -> None:
    sparse = (await client.get(ENDPOINT, params={"support": "SPARSE", "limit": 5})).json()
    assert all(row["waiting_count"] < 20 for row in sparse["items"])


@pytest.mark.anyio
async def test_region_filter_keeps_only_that_region(client: httpx.AsyncClient, busiest: dict) -> None:
    region = busiest["region_code"]
    body = (await client.get(ENDPOINT, params={"region": region, "limit": 500})).json()
    assert body["items"]
    assert {row["region_code"] for row in body["items"]} == {region}


@pytest.mark.anyio
async def test_unknown_region_returns_an_empty_page(client: httpx.AsyncClient) -> None:
    body = (await client.get(ENDPOINT, params={"region": "ZZ"})).json()
    assert body["total"] == 0 and body["items"] == []


# ------------------------------------------------------------------------------------- referral list


@pytest.mark.anyio
async def test_referrals_match_the_hospital_count(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals", params={"limit": 5})).json()
    assert body["total"] == busiest["waiting_count"]
    assert len(body["items"]) == 5


@pytest.mark.anyio
async def test_no_referral_was_registered_after_the_origin(client: httpx.AsyncClient, busiest: dict) -> None:
    origin = dt.date.fromisoformat(busiest["origin"])
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals", params={"limit": 500})).json()
    for row in body["items"]:
        assert dt.date.fromisoformat(row["registration_date"]) <= origin
        assert row["days_waited_at_origin"] == (origin - dt.date.fromisoformat(row["registration_date"])).days


@pytest.mark.anyio
async def test_day_hospital_referrals_are_absent(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals", params={"limit": 500})).json()
    assert all(row["profile_code"] != "DH" for row in body["items"])


@pytest.mark.anyio
async def test_order_is_by_days_waited_both_ways(client: httpx.AsyncClient, busiest: dict) -> None:
    url = f"{ENDPOINT}/{busiest['org_code']}/referrals"
    longest = (await client.get(url, params={"limit": 50})).json()["items"]
    shortest = (await client.get(url, params={"limit": 50, "order": "shortest_wait"})).json()["items"]
    assert [row["days_waited_at_origin"] for row in longest] == sorted(
        [row["days_waited_at_origin"] for row in longest], reverse=True
    )
    assert [row["days_waited_at_origin"] for row in shortest] == sorted(
        [row["days_waited_at_origin"] for row in shortest]
    )
    assert longest[0]["days_waited_at_origin"] == busiest["max_days_waited"]


@pytest.mark.anyio
async def test_pagination_does_not_repeat_or_skip_rows(client: httpx.AsyncClient, busiest: dict) -> None:
    url = f"{ENDPOINT}/{busiest['org_code']}/referrals"
    first = (await client.get(url, params={"limit": 10})).json()["items"]
    second = (await client.get(url, params={"limit": 10, "offset": 10})).json()["items"]
    ids = [row["referral_id"] for row in [*first, *second]]
    assert len(ids) == len(set(ids)) == 20


@pytest.mark.anyio
async def test_profile_filter_narrows_the_list(client: httpx.AsyncClient, busiest: dict) -> None:
    url = f"{ENDPOINT}/{busiest['org_code']}/referrals"
    sample = (await client.get(url, params={"limit": 1})).json()["items"][0]
    body = (await client.get(url, params={"profile": sample["profile_code"], "limit": 500})).json()
    assert body["items"]
    assert {row["profile_code"] for row in body["items"]} == {sample["profile_code"]}
    assert body["total"] <= busiest["waiting_count"]


@pytest.mark.anyio
async def test_unknown_hospital_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{ENDPOINT}/NOSUCHRG/referrals")).status_code == 404


# ------------------------------------------------------------------------------------- hindsight field


@pytest.mark.anyio
async def test_every_referral_marks_its_hindsight_and_stays_consistent(
    client: httpx.AsyncClient, busiest: dict
) -> None:
    origin = dt.date.fromisoformat(busiest["origin"])
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals", params={"limit": 500})).json()
    for row in body["items"]:
        observed = row["observed_after_origin"]
        assert observed["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
        assert observed["status"] in {"ADMITTED", "REFUSED", "STILL_WAITING_AT_CUTOFF"}
        if observed["status"] == "STILL_WAITING_AT_CUTOFF":
            assert observed["event_date"] is None and observed["days_from_origin"] is None
        else:
            event = dt.date.fromisoformat(observed["event_date"])
            assert event > origin
            assert observed["days_from_origin"] == (event - origin).days


@pytest.mark.anyio
async def test_no_model_value_is_served_anywhere(client: httpx.AsyncClient, busiest: dict) -> None:
    """The A1 promise: this view carries zero model output, so there is nothing here to leak."""
    hospital = (await client.get(ENDPOINT, params={"limit": 1})).json()["items"][0]
    referral = (await client.get(f"{ENDPOINT}/{busiest['org_code']}/referrals", params={"limit": 1})).json()["items"][0]
    forbidden = ("pred", "probability", "severity", "forecast", "score", "risk", "calibration", "model_version")
    for payload in (hospital, referral):
        offenders = [key for key in payload if any(token in key for token in forbidden)]
        assert not offenders, f"model-bearing field served by the waiting list: {offenders}"
    assert "explanation" not in referral


# ------------------------------------------------------------------------------------- hospital detail


@pytest.mark.anyio
async def test_hospital_detail_agrees_with_its_own_list_row(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}")).json()
    for key in ("org_code", "waiting_count", "profile_count", "max_days_waited", "support_class"):
        assert body[key] == busiest[key]


@pytest.mark.anyio
async def test_profile_breakdown_sums_to_the_hospital_total(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}")).json()
    assert len(body["profiles"]) == body["profile_count"]
    assert sum(p["waiting_count"] for p in body["profiles"]) == body["waiting_count"]
    counts = [p["waiting_count"] for p in body["profiles"]]
    assert counts == sorted(counts, reverse=True)
    assert all(p["profile_code"] != "DH" for p in body["profiles"])


@pytest.mark.anyio
async def test_histogram_covers_every_referral_exactly_once(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}")).json()
    buckets = body["days_waited_histogram"]
    assert sum(b["count"] for b in buckets) == body["waiting_count"]
    assert buckets[0]["from_days"] == 0
    assert buckets[-1]["to_days"] is None
    for earlier, later in zip(buckets, buckets[1:], strict=False):
        assert earlier["to_days"] == later["from_days"], "buckets must be contiguous"


@pytest.mark.anyio
async def test_hindsight_totals_are_marked_and_complete(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}")).json()
    observed = body["observed_after_origin"]
    assert observed["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
    assert observed["admitted"] + observed["refused"] + observed["still_waiting_at_cutoff"] == body["waiting_count"]


@pytest.mark.anyio
async def test_hospital_detail_carries_no_model_value(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{ENDPOINT}/{busiest['org_code']}")).json()
    forbidden = ("pred", "probability", "severity", "forecast", "score", "risk", "calibration")
    assert not [key for key in body if any(token in key for token in forbidden)]
    assert not [key for key in body["profiles"][0] if any(token in key for token in forbidden)]


@pytest.mark.anyio
async def test_unknown_hospital_detail_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{ENDPOINT}/NOSUCHRG")).status_code == 404
