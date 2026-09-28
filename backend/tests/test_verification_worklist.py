"""Verification-worklist endpoints against the running database (`make seed-load` or the publish targets).

The edge is where the framing is most easily lost, so these tests hold it there: the framing fields arrive on
every response, the order ranks the whole formal queue and subtracts nothing from it, the measured queue is provably
untouched, the served order is the published one, no row carries an outcome, and the yield curve stays hindsight.
"""

import httpx
import pytest

from tests.conftest import API, auth

PUBLICATION = f"{API}/verification-worklist/publication"
REGIONS = f"{API}/verification-worklist/regions"
HOSPITALS = f"{API}/verification-worklist/hospitals"
WAITING = f"{API}/waiting-list/hospitals"


@pytest.fixture(scope="module", autouse=True)
async def publication(client: httpx.AsyncClient) -> dict:
    response = await client.get(PUBLICATION)
    if response.status_code == 404:
        pytest.skip("no verification-worklist publication is active (run `make verification-worklist-publish`)")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
async def busiest(client: httpx.AsyncClient) -> dict:
    body = (await client.get(WAITING, params={"limit": 1})).json()
    if not body.get("items"):
        pytest.skip("no waiting-list publication is active")
    return body["items"][0]


@pytest.fixture(scope="module")
async def worklist(client: httpx.AsyncClient, busiest: dict) -> dict:
    return (await client.get(f"{HOSPITALS}/{busiest['org_code']}", params={"limit": 200})).json()


# ------------------------------------------------------------------------------------- access control


@pytest.mark.anyio
async def test_every_endpoint_requires_a_key(anon_client: httpx.AsyncClient, busiest: dict) -> None:
    assert (await anon_client.get(PUBLICATION)).status_code == 401
    assert (await anon_client.get(REGIONS)).status_code == 401
    assert (await anon_client.get(f"{HOSPITALS}/{busiest['org_code']}")).status_code == 401


@pytest.mark.anyio
async def test_viewer_role_is_enough(anon_client: httpx.AsyncClient, api_keys: dict[str, str], busiest: dict) -> None:
    headers = auth(api_keys["viewer"])
    for url in (PUBLICATION, REGIONS, f"{HOSPITALS}/{busiest['org_code']}"):
        assert (await anon_client.get(url, headers=headers)).status_code == 200


# ------------------------------------------------------------------------------------- it is not a decision


@pytest.mark.anyio
async def test_every_response_says_who_decides(publication: dict, worklist: dict) -> None:
    for payload in (publication, worklist):
        assert payload["decision_owner"] == "SPECIALIST_DECIDES"
        # both interface languages: a sentence the reader cannot read does not frame anything
        assert payload["not_a_decision"]["ru"].strip()
        assert payload["not_a_decision"]["kk"].strip()
    for row in worklist["items"]:
        assert row["decision_owner"] == "SPECIALIST_DECIDES"
        assert row["not_a_decision"] == worklist["not_a_decision"]


@pytest.mark.anyio
async def test_no_response_field_suggests_removing_anyone(worklist: dict) -> None:
    """A review list must not grow a field that reads as an instruction to act on a patient."""
    forbidden = ("delete", "remove", "exclude", "drop", "purge", "ghost", "fake", "fictitious")
    payload = {*worklist, *(worklist["items"][0] if worklist["items"] else {})}
    offenders = [key for key in payload if any(token in key.lower() for token in forbidden)]
    assert not offenders, f"worklist serves a field that reads as a decision: {offenders}"


# ------------------------------------------------------------------------------------- it is not a queue


@pytest.mark.anyio
async def test_the_order_ranks_the_whole_formal_queue(
    publication: dict, worklist: dict, client: httpx.AsyncClient
) -> None:
    assert publication["counts"]["ranked_count"] == publication["counts"]["formal_queue_count"]
    assert worklist["total"] == worklist["formal_queue_count"]
    for row in (await client.get(REGIONS)).json():
        assert row["formal_queue_count"] >= row["history_quality_warning_count"]


@pytest.mark.anyio
async def test_the_hospital_counts_agree_with_the_measured_queue(worklist: dict, busiest: dict) -> None:
    """The worklist's denominator is the queue itself, not a number of its own."""
    assert worklist["formal_queue_count"] == busiest["waiting_count"]


@pytest.mark.anyio
async def test_publishing_a_worklist_leaves_the_measured_queue_untouched(
    client: httpx.AsyncClient, busiest: dict, worklist: dict
) -> None:
    queue = (await client.get(f"{WAITING}/{busiest['org_code']}")).json()
    assert queue["waiting_count"] == busiest["waiting_count"]
    assert queue["waiting_count"] == worklist["total"]
    assert not any("priority" in key or "history_quality" in key for key in queue)


@pytest.mark.anyio
async def test_the_region_rows_account_for_the_whole_publication(client: httpx.AsyncClient, publication: dict) -> None:
    rows = (await client.get(REGIONS)).json()
    assert sum(row["history_quality_warning_count"] for row in rows) == publication["history_quality"]["warning_count"]
    assert sum(row["formal_queue_count"] for row in rows) == publication["counts"]["formal_queue_count"]
    counts = [row["formal_queue_count"] for row in rows]
    assert counts == sorted(counts, reverse=True)
    assert all(row["name"] and row["level"] == "region" for row in rows)


# ------------------------------------------------------------------------------------- the order and the marks


@pytest.mark.anyio
async def test_the_published_order_is_what_the_page_serves(worklist: dict) -> None:
    ranks = [row["rank"] for row in worklist["items"]]
    assert ranks == sorted(ranks)
    scores = [row["verification_priority_score"] for row in worklist["items"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.anyio
async def test_no_served_row_carries_an_outcome(worklist: dict) -> None:
    """Hindsight lives in the yield curve only; a row is what was knowable at the origin."""
    for row in worklist["items"]:
        assert not any(token in key for key in row for token in ("status", "outcome", "observed", "admitted_at"))


@pytest.mark.anyio
async def test_a_warning_row_names_its_reason(publication: dict, worklist: dict) -> None:
    reasons = set(publication["history_quality"]["reason_counts"])
    for row in worklist["items"]:
        assert row["history_quality_warning"] == (row["history_quality_reason_code"] is not None)
        assert row["history_quality_reason_code"] is None or row["history_quality_reason_code"] in reasons


@pytest.mark.anyio
async def test_the_wait_order_is_offered_too(client: httpx.AsyncClient, busiest: dict) -> None:
    body = (await client.get(f"{HOSPITALS}/{busiest['org_code']}", params={"order": "longest_wait"})).json()
    waits = [row["days_waited_at_origin"] for row in body["items"]]
    assert waits == sorted(waits, reverse=True)


@pytest.mark.anyio
async def test_the_history_warning_filter_keeps_only_marked_rows(
    client: httpx.AsyncClient, busiest: dict, worklist: dict
) -> None:
    url = f"{HOSPITALS}/{busiest['org_code']}"
    marked = (await client.get(url, params={"history_quality_warning": "true", "limit": 200})).json()
    assert all(row["history_quality_warning"] for row in marked["items"])
    rest = (await client.get(url, params={"history_quality_warning": "false", "limit": 200})).json()
    assert not any(row["history_quality_warning"] for row in rest["items"])
    assert marked["total"] + rest["total"] == worklist["total"]


@pytest.mark.anyio
async def test_each_row_carries_what_the_bureau_needs_to_find_the_record(worklist: dict) -> None:
    for row in worklist["items"]:
        assert row["profile_name"]
        # the queue supplies these; they are null only when the current publication no longer carries the referral
        assert row["hospitalization_code"] is None or row["hospitalization_code"].strip()
        assert row["registration_date"] is None or row["registration_date"].startswith("202")


@pytest.mark.anyio
async def test_pagination_does_not_repeat_or_skip_rows(client: httpx.AsyncClient, busiest: dict) -> None:
    url = f"{HOSPITALS}/{busiest['org_code']}"
    first = (await client.get(url, params={"limit": 10})).json()["items"]
    second = (await client.get(url, params={"limit": 10, "offset": 10})).json()["items"]
    ids = [row["referral_id"] for row in [*first, *second]]
    assert len(ids) == len(set(ids)) == 20


@pytest.mark.anyio
async def test_unknown_hospital_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{HOSPITALS}/NOSUCHRG")).status_code == 404


# ------------------------------------------------------------------------------------- the yield curve


@pytest.mark.anyio
async def test_the_yield_curve_is_hindsight_and_internally_consistent(publication: dict) -> None:
    curve = publication["yield_curve"]
    assert curve["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
    assert curve["outcome_source"].startswith("waiting-list-")
    assert len(curve["outcome_source_identity_sha256"]) == 64
    base = curve["base"]
    assert base["evaluated"] == publication["counts"]["formal_queue_count"]
    checked = [point["checked"] for point in curve["points"]]
    assert checked == sorted(set(checked))
    for point in curve["points"]:
        assert 0 <= point["no_longer_current"] <= point["checked"]
        assert abs(point["share"] - point["no_longer_current"] / point["checked"]) < 1e-6
        assert abs(point["lift"] - point["share"] / base["share"]) < 1e-5
        assert point["checked"] <= publication["counts"]["ranked_count"]


@pytest.mark.anyio
async def test_the_yield_curve_matches_the_waiting_list_it_names(client: httpx.AsyncClient, publication: dict) -> None:
    """The outcomes were read from a publication that is actually serving, not from a stale copy."""
    snapshot = (await client.get(f"{WAITING}", params={"limit": 1})).json()["items"][0]
    assert publication["yield_curve"]["outcome_source"] == snapshot["publication_id"]
    assert publication["yield_curve"]["outcome_source_identity_sha256"] == snapshot["publication_identity_sha256"]


@pytest.mark.anyio
async def test_the_hospital_counts_are_all_that_hospitals_own(
    client: httpx.AsyncClient, busiest: dict, worklist: dict, publication: dict
) -> None:
    """A totals row that mixes one hospital with the whole country is the easiest way to mislead a reader."""
    marked = (
        await client.get(f"{HOSPITALS}/{busiest['org_code']}", params={"history_quality_warning": "true", "limit": 500})
    ).json()
    assert worklist["history_quality_warning_count"] == marked["total"]
    assert worklist["history_quality_warning_count"] <= worklist["formal_queue_count"]
    assert worklist["history_quality_warning_count"] <= publication["history_quality"]["warning_count"]


@pytest.mark.anyio
async def test_every_screen_sentence_arrives_in_both_languages(publication: dict) -> None:
    for sentence in (
        publication["not_a_decision"],
        publication["legacy_rule"]["statement"],
        publication["ranking"]["definition"],
        publication["history_quality"]["definition"],
        publication["yield_curve"]["definition"],
    ):
        assert sentence["ru"].strip() and sentence["kk"].strip()


@pytest.mark.anyio
async def test_the_history_warning_is_published_with_its_reasons(publication: dict) -> None:
    quality = publication["history_quality"]
    assert quality["definition"]["ru"].strip() and quality["definition"]["kk"].strip()
    assert sum(quality["reason_counts"].values()) == quality["warning_count"]
    assert 0 <= quality["warning_count"] <= publication["counts"]["formal_queue_count"]


@pytest.mark.anyio
async def test_the_legacy_rule_is_a_reference_not_the_selector(publication: dict) -> None:
    legacy = publication["legacy_rule"]
    assert legacy["role"] == "AUDITED_REFERENCE_ONLY"
    assert legacy["selected_count"] < publication["counts"]["ranked_count"]
