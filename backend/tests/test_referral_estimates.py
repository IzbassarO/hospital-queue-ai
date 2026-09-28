"""Per-referral estimate endpoints against the running database (`make seed-load` or the publish targets).

What the edge has to guarantee, and what these tests hold:
  * viewer role is enough, and an anonymous caller gets nothing;
  * every row carries both publications, each with its own id and identity, and the measured half is unchanged;
  * the estimates are coherent on the wire, not only in the builder;
  * abstention arrives as a reason, never as a blank, and a collapsed 30-day estimate is flagged as thin
    evidence rather than served as a confident 0% or 100%;
  * the administrative order and filter agree with the published threshold, exactly;
  * the tournament and the calibration served to the screen are the published ones.
"""

import datetime as dt

import httpx
import pytest

from tests.conftest import API, auth

PUBLICATION = f"{API}/referral-estimates/publication"
QUEUE = f"{API}/referral-estimates/hospitals"
WAITING = f"{API}/waiting-list/hospitals"


@pytest.fixture(scope="module", autouse=True)
async def publication(client: httpx.AsyncClient) -> dict:
    """The active publication, or the whole module skips (the CI fixture publishes nothing)."""
    response = await client.get(PUBLICATION)
    if response.status_code == 404:
        pytest.skip("no referral-estimates publication is active (run `make referral-estimates-publish`)")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
async def busiest(client: httpx.AsyncClient) -> dict:
    body = (await client.get(WAITING, params={"limit": 1})).json()
    if not body.get("items"):
        pytest.skip("no waiting-list publication is active")
    return body["items"][0]


@pytest.fixture(scope="module")
async def small(client: httpx.AsyncClient) -> dict:
    """A hospital whose whole queue fits in one page, so a count can be asserted exactly."""
    body = (await client.get(WAITING, params={"support": "SPARSE", "limit": 1})).json()
    if not body.get("items"):
        pytest.skip("the waiting list has no small hospital to count exactly")
    return body["items"][0]


@pytest.fixture(scope="module")
async def rows(client: httpx.AsyncClient, busiest: dict) -> list[dict]:
    body = (await client.get(f"{QUEUE}/{busiest['org_code']}/referrals", params={"limit": 500})).json()
    return body["items"]


# ------------------------------------------------------------------------------------- access control


@pytest.mark.anyio
async def test_both_endpoints_require_a_key(anon_client: httpx.AsyncClient, busiest: dict) -> None:
    assert (await anon_client.get(PUBLICATION)).status_code == 401
    assert (await anon_client.get(f"{QUEUE}/{busiest['org_code']}/referrals")).status_code == 401


@pytest.mark.anyio
async def test_viewer_role_is_enough(anon_client: httpx.AsyncClient, api_keys: dict[str, str], busiest: dict) -> None:
    headers = auth(api_keys["viewer"])
    assert (await anon_client.get(PUBLICATION, headers=headers)).status_code == 200
    queue = await anon_client.get(f"{QUEUE}/{busiest['org_code']}/referrals", headers=headers)
    assert queue.status_code == 200


# ------------------------------------------------------------------------------------- the publication


@pytest.mark.anyio
async def test_the_publication_stands_at_the_waiting_list_origin(publication: dict, busiest: dict) -> None:
    assert publication["origin"] == busiest["origin"]
    assert publication["matches_waiting_list"] is True
    assert publication["horizons"] == [7, 14, 30]
    assert len(publication["publication_identity_sha256"]) == 64


@pytest.mark.anyio
async def test_the_tournament_names_one_baseline_and_a_rule_fixed_in_advance(publication: dict) -> None:
    selection = publication["selection"]
    roles = [row["role"] for row in selection["candidates"]]
    assert roles.count("baseline") == 1
    assert len(selection["candidates"]) >= 2
    assert selection["decision_rule"].strip()
    assert selection["selected_model"] in {row["model_key"] for row in selection["candidates"]}
    if selection["fallback_used"]:
        assert not any(row["accepted"] for row in selection["candidates"])


@pytest.mark.anyio
async def test_the_calibration_is_marked_as_hindsight_and_describes_the_served_model(publication: dict) -> None:
    calibration = publication["calibration"]
    assert calibration["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
    assert calibration["model_key"] == publication["selection"]["selected_model"]
    horizons = {row["horizon_days"] for row in calibration["bins"]}
    assert horizons <= set(publication["horizons"])
    for row in calibration["bins"]:
        assert 0 <= row["mean_predicted"] <= 1
        assert 0 <= row["observed_rate"] <= 1
        assert row["n"] >= 1


@pytest.mark.anyio
async def test_the_follow_up_threshold_is_published_with_what_it_is_for(publication: dict) -> None:
    attention = publication["attention"]
    assert attention["metric"] == "refused_30d"
    assert 0 < attention["threshold"] < 1
    assert attention["definition"].strip() and attention["intended_use"].strip()
    assert attention["flagged_count"] >= 1


@pytest.mark.anyio
async def test_every_tier_and_abstention_count_sums_to_the_publication(publication: dict) -> None:
    assert sum(publication["estimate_tiers"].values()) == publication["referral_count"]
    assert sum(publication["abstention_counts"].values()) <= publication["referral_count"]


# ------------------------------------------------------------------------------------- the joined queue


@pytest.mark.anyio
async def test_the_queue_is_the_same_cohort_as_the_measured_publication(
    client: httpx.AsyncClient, busiest: dict
) -> None:
    joined = (await client.get(f"{QUEUE}/{busiest['org_code']}/referrals", params={"limit": 1})).json()
    measured = (await client.get(f"{WAITING}/{busiest['org_code']}/referrals", params={"limit": 1})).json()
    assert joined["total"] == measured["total"] == busiest["waiting_count"]
    assert joined["items"][0]["referral_id"] == measured["items"][0]["referral_id"]


@pytest.mark.anyio
async def test_each_row_carries_both_publications_separately(rows: list[dict], publication: dict) -> None:
    for row in rows:
        assert row["publication_id"].startswith("waiting-list-")
        assert row["observed_after_origin"]["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
        estimate = row["estimate"]
        if estimate is None:
            continue
        assert estimate["publication_id"] == publication["publication_id"]
        assert estimate["publication_identity_sha256"] == publication["publication_identity_sha256"]
        assert estimate["origin"] == row["origin"]


@pytest.mark.anyio
async def test_the_estimates_are_coherent_on_the_wire(rows: list[dict]) -> None:
    covered = [row["estimate"] for row in rows if row["estimate"]]
    assert covered, "the publication covers none of this hospital's queue"
    for estimate in covered:
        assert estimate["admitted_7d"] <= estimate["admitted_14d"] <= estimate["admitted_30d"]
        assert estimate["admitted_30d"] + estimate["refused_30d"] <= 1 + 1e-6
        assert estimate["still_waiting_30d"] == pytest.approx(
            max(0.0, 1 - estimate["admitted_30d"] - estimate["refused_30d"]), abs=1e-6
        )


@pytest.mark.anyio
async def test_no_estimate_depends_on_an_outcome_recorded_after_the_origin(rows: list[dict]) -> None:
    """Origin-time means origin-time: identical inputs must not produce different numbers by later outcome."""
    by_key: dict[tuple, set[tuple]] = {}
    for row in rows:
        estimate = row["estimate"]
        if estimate is None:
            continue
        key = (row["profile_code"], row["days_waited_at_origin"], estimate["estimate_tier"])
        by_key.setdefault(key, set()).add(
            (estimate["admitted_7d"], estimate["admitted_14d"], estimate["admitted_30d"], estimate["refused_30d"])
        )
    disagreeing = {key: values for key, values in by_key.items() if len(values) > 1}
    assert not disagreeing, f"same origin-time inputs, different estimates: {list(disagreeing)[:3]}"


@pytest.mark.anyio
async def test_an_absent_admission_window_arrives_as_a_reason(rows: list[dict], publication: dict) -> None:
    reasons = set(publication["abstention_counts"])
    for row in rows:
        estimate = row["estimate"]
        if estimate is None:
            continue
        has_window = estimate["window_lower_days"] is not None
        assert has_window == (estimate["abstention_reason"] is None)
        if not has_window:
            assert estimate["abstention_reason"] in reasons
        else:
            assert estimate["window_lower_days"] <= estimate["window_upper_days"]
            assert estimate["window_coverage"] == publication["admission_window_coverage"]


@pytest.mark.anyio
async def test_every_row_says_where_its_evidence_came_from(rows: list[dict], publication: dict) -> None:
    tiers = set(publication["estimate_tiers"])
    for row in rows:
        if row["estimate"]:
            assert row["estimate"]["estimate_tier"] in tiers


@pytest.mark.anyio
async def test_a_collapsed_estimate_is_flagged_and_counted(rows: list[dict], publication: dict) -> None:
    """The longest-waiting referrals are where the curve runs out of history; the API must admit it."""
    degeneracy = publication["degeneracy"]
    assert degeneracy["definition"].strip()
    assert degeneracy["count"] == sum(degeneracy["by_outcome"].values())
    assert 0 < degeneracy["count"] < publication["referral_count"]
    for row in rows:
        estimate = row["estimate"]
        if estimate is None:
            continue
        collapsed = max(estimate["admitted_30d"], estimate["refused_30d"], estimate["still_waiting_30d"]) >= 1 - 1e-6
        assert estimate["degenerate_30d"] is collapsed


@pytest.mark.anyio
async def test_the_default_order_is_where_the_flag_matters_most(client: httpx.AsyncClient, busiest: dict) -> None:
    """Longest wait is the default order and the thinnest evidence; that page must carry the flag, not hide it."""
    url = f"{QUEUE}/{busiest['org_code']}/referrals"
    page = (await client.get(url, params={"limit": 25})).json()["items"]
    covered = [row for row in page if row["estimate"]]
    assert covered
    assert any(row["estimate"]["degenerate_30d"] for row in covered)


# ------------------------------------------------------------------------------------- order and filter


@pytest.mark.anyio
async def test_the_measured_orders_still_work_unchanged(client: httpx.AsyncClient, busiest: dict) -> None:
    url = f"{QUEUE}/{busiest['org_code']}/referrals"
    longest = (await client.get(url, params={"limit": 50})).json()["items"]
    shortest = (await client.get(url, params={"limit": 50, "order": "shortest_wait"})).json()["items"]
    waits = [row["days_waited_at_origin"] for row in longest]
    assert waits == sorted(waits, reverse=True)
    assert longest[0]["days_waited_at_origin"] == busiest["max_days_waited"]
    rising = [row["days_waited_at_origin"] for row in shortest]
    assert rising == sorted(rising)


@pytest.mark.anyio
async def test_the_refusal_order_is_descending_and_puts_the_unknown_last(
    client: httpx.AsyncClient, busiest: dict
) -> None:
    url = f"{QUEUE}/{busiest['org_code']}/referrals"
    items = (await client.get(url, params={"limit": 50, "order": "highest_refusal_risk"})).json()["items"]
    risks = [row["estimate"]["refused_30d"] if row["estimate"] else None for row in items]
    known = [value for value in risks if value is not None]
    assert known == sorted(known, reverse=True)
    assert risks.index(None) > len(known) - 1 if None in risks else True


@pytest.mark.anyio
async def test_the_attention_filter_is_exactly_the_published_threshold(
    client: httpx.AsyncClient, small: dict, publication: dict
) -> None:
    url = f"{QUEUE}/{small['org_code']}/referrals"
    threshold = publication["attention"]["threshold"]
    whole = (await client.get(url, params={"limit": 500})).json()
    assert whole["total"] == small["waiting_count"] <= 500, "this check needs the whole queue in one page"
    flagged = (await client.get(url, params={"limit": 500, "attention": "true"})).json()
    for row in flagged["items"]:
        assert row["estimate"]["refusal_attention"] is True
        assert row["estimate"]["refused_30d"] >= threshold
    expected = sum(1 for row in whole["items"] if row["estimate"] and row["estimate"]["refused_30d"] >= threshold)
    assert flagged["total"] == expected


@pytest.mark.anyio
async def test_pagination_does_not_repeat_or_skip_rows(client: httpx.AsyncClient, busiest: dict) -> None:
    url = f"{QUEUE}/{busiest['org_code']}/referrals"
    first = (await client.get(url, params={"limit": 10})).json()["items"]
    second = (await client.get(url, params={"limit": 10, "offset": 10})).json()["items"]
    ids = [row["referral_id"] for row in [*first, *second]]
    assert len(ids) == len(set(ids)) == 20


@pytest.mark.anyio
async def test_the_profile_filter_narrows_both_halves_of_the_row(
    client: httpx.AsyncClient, busiest: dict, rows: list[dict]
) -> None:
    url = f"{QUEUE}/{busiest['org_code']}/referrals"
    profile = rows[0]["profile_code"]
    body = (await client.get(url, params={"profile": profile, "limit": 500})).json()
    assert body["items"]
    assert {row["profile_code"] for row in body["items"]} == {profile}
    assert body["total"] <= busiest["waiting_count"]
    assert any(row["estimate"] for row in body["items"]), "a filtered page lost its estimates"


@pytest.mark.anyio
async def test_unknown_hospital_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{QUEUE}/NOSUCHRG/referrals")).status_code == 404


@pytest.mark.anyio
async def test_the_origin_of_every_row_is_the_publication_origin(rows: list[dict], publication: dict) -> None:
    origin = dt.date.fromisoformat(publication["origin"])
    for row in rows:
        assert dt.date.fromisoformat(row["registration_date"]) <= origin
