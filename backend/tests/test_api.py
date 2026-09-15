"""Every endpoint: status 200 and the expected shape; the recommendation rule; decisions persistence;
latency budget for the live demo."""

import datetime as dt
import re
import time
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.db.session import SessionLocal
from conftest import API, TEST_ACTOR_PREFIX

pytestmark = pytest.mark.anyio

STATUS_METRIC_KEYS = {
    "as_of_date",
    "queue_now",
    "registrations_28d",
    "hospitalizations_28d",
    "refusals_28d",
    "refusal_rate_28d",
    "n_waits_28d",
    "median_wait_28d",
    "daily_throughput_28d",
    "backlog_days",
    "forecast_registrations_14d",
    "forecast_hospitalizations_14d",
    "n_test_referrals",
    "high_risk_share",
    "queue_trend_raw_4w",
    "queue_trend_4w",
    "has_sufficient_data",
    "load_index",
    "status",
    "status_label",
    "components",
}
AREA_KEYS = {
    "code",
    "name",
    "level",
    "queue_now",
    "registrations_28d",
    "hospitalizations_28d",
    "refusals_28d",
    "refusal_rate_28d",
    "median_wait_28d",
    "n_waits_28d",
    "forecast_registrations_14d",
    "forecast_hospitalizations_14d",
    "high_risk_share",
    "n_hospitals",
    "n_hospital_profiles",
    "n_hospital_profiles_ranked",
    "load_index_max",
    "n_hospitals_high_load",
    "n_hospital_profiles_high_load",
}


async def get_json(client: httpx.AsyncClient, path: str, **params):
    response = await client.get(f"{API}{path}", params=params)
    assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
    return response.json()


def assert_page(body: dict, limit: int, offset: int = 0) -> None:
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["limit"] == limit and body["offset"] == offset
    assert len(body["items"]) <= limit
    assert body["total"] >= len(body["items"])


def assert_ranked(items: list[dict]) -> None:
    indexes = [i["load_index"] for i in items]
    ranked = [x for x in indexes if x is not None]
    assert ranked == sorted(ranked, reverse=True), "not sorted by load_index desc"
    if None in indexes:
        assert all(x is None for x in indexes[indexes.index(None) :]), "rows without load_index must come last"


# ------------------------------------------------------------------------------------------ service
async def test_health(client):
    body = await get_json(client, "/health")
    assert body["status"] == "ok" and body["database"] == "ok"
    assert dt.date.fromisoformat(body["marts_as_of_date"]) == dt.date(2025, 3, 31)


async def test_cors_allows_localhost_dev_ports_only(client):
    headers = {"Access-Control-Request-Method": "GET"}
    ok = await client.options(f"{API}/overview", headers={**headers, "Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    blocked = await client.options(f"{API}/overview", headers={**headers, "Origin": "https://example.com"})
    assert "access-control-allow-origin" not in blocked.headers


# ------------------------------------------------------------------------------------------ monitoring
async def test_overview(client):
    body = await get_json(client, "/overview")
    assert set(body) == {"as_of_date", "built_at", "thresholds", "national", "regions"}
    assert body["as_of_date"] == "2025-03-31"
    assert set(body["national"]) == AREA_KEYS and body["national"]["code"] == "KZ"
    regions = body["regions"]
    dictionary = await get_json(client, "/dictionaries")
    # every region with data (all 20 on the full data, 2 on the CI fixture), each a known region
    assert 1 <= len(regions) <= len(dictionary["regions"])
    assert {r["code"] for r in regions} <= {r["code"] for r in dictionary["regions"]}
    assert all(set(r) == AREA_KEYS and r["level"] == "region" and r["name"] for r in regions)
    assert sum(r["queue_now"] for r in regions) == body["national"]["queue_now"]
    assert sum(r["n_hospitals_high_load"] for r in regions) == body["national"]["n_hospitals_high_load"]
    assert max(r["load_index_max"] for r in regions) == body["national"]["load_index_max"]


async def test_queue_trend_is_excess_over_national_median(client, high_load):
    """queue_trend_4w = queue_trend_raw_4w − national median raw trend; the trend score uses the excess,
    floored at 0."""
    median = (await get_json(client, "/overview"))["thresholds"]["queue_trend_national_median_4w"]
    assert median is not None
    hospitals = await get_json(client, f"/regions/{high_load['region_code']}/hospitals", limit=500)
    rows = [h for h in hospitals["items"] if h["queue_trend_4w"] is not None]
    assert rows
    for h in rows:
        assert h["queue_trend_raw_4w"] - h["queue_trend_4w"] == pytest.approx(median, abs=0.11)
        if h["has_sufficient_data"] and h["queue_trend_4w"] <= 0:
            assert h["components"]["trend_score"] == 0


async def test_region_detail(client, high_load):
    body = await get_json(client, f"/regions/{high_load['region_code']}")
    assert set(body) == {"region", "profiles"}
    assert body["region"]["code"] == high_load["region_code"] and set(body["region"]) == AREA_KEYS
    assert body["profiles"], "a region has profiles"
    for p in body["profiles"]:
        assert set(p) >= STATUS_METRIC_KEYS
        assert p["region_code"] == high_load["region_code"] and p["profile_name"]
        assert (p["load_index"] is None) == (p["status"] == "insufficient_data")
    assert_ranked(body["profiles"])


async def test_unknown_codes_return_404(client):
    assert (await client.get(f"{API}/regions/00")).status_code == 404
    assert (await client.get(f"{API}/regions/71/hospitals", params={"profile": "nope"})).status_code == 404
    assert (await client.get(f"{API}/hospitals/NOPE/profiles/021")).status_code == 404


async def test_region_hospitals_ranked_and_paginated(client, high_load):
    region, profile = high_load["region_code"], high_load["profile_code"]
    body = await get_json(client, f"/regions/{region}/hospitals", limit=5)
    assert_page(body, 5)
    assert_ranked(body["items"])
    for item in body["items"]:
        assert set(item) >= STATUS_METRIC_KEYS and item["region_code"] == region and item["org_name"]

    second = await get_json(client, f"/regions/{region}/hospitals", limit=5, offset=5)
    assert_page(second, 5, 5)
    assert second["total"] == body["total"]
    first_keys = {(i["org_code"], i["profile_code"]) for i in body["items"]}
    assert not first_keys & {(i["org_code"], i["profile_code"]) for i in second["items"]}

    filtered = await get_json(client, f"/regions/{region}/hospitals", profile=profile, limit=500)
    assert filtered["items"] and all(i["profile_code"] == profile for i in filtered["items"])
    assert_ranked(filtered["items"])


async def test_hospital_profile_card(client, high_load):
    org, profile = high_load["org_code"], high_load["profile_code"]
    body = await get_json(client, f"/hospitals/{org}/profiles/{profile}")
    assert set(body) == {"status", "series", "forecast", "explanation_factors"}

    status = body["status"]
    assert set(status) >= STATUS_METRIC_KEYS
    assert (status["org_code"], status["profile_code"]) == (org, profile)
    assert status["load_index"] == high_load["load_index"]

    dates = [dt.date.fromisoformat(p["date"]) for p in body["series"]]
    assert dates[0] == dt.date(2025, 2, 2) and dates[-1] == dt.date(2025, 3, 31)
    assert len(dates) == (dates[-1] - dates[0]).days + 1, "daily series must be dense"
    assert set(body["series"][0]) == {"date", "registrations", "hospitalizations", "refusals", "queue"}
    assert body["series"][-1]["queue"] == status["queue_now"]

    forecast = body["forecast"]
    assert [p["horizon"] for p in forecast["points"]] == list(range(1, 15))
    assert forecast["points"][0]["date"] == "2025-04-01" and forecast["origin_date"] == "2025-03-31"
    assert set(forecast["points"][0]) == {"date", "horizon", "registrations", "hospitalizations"}
    total = sum(p["registrations"] for p in forecast["points"])
    assert total == pytest.approx(status["forecast_registrations_14d"], abs=0.2)

    factors = body["explanation_factors"]
    assert factors["n_referrals"] == status["n_test_referrals"] > 0
    for model, unit in (("wait_time", "дн."), ("refusal_risk", "п.п.")):
        rows = factors[model]
        assert 1 <= len(rows) <= 5
        assert all(r["unit"] == unit and r["label"] and 0 < r["share_in_top5"] <= 1 for r in rows)
        assert [r["mean_abs_effect"] for r in rows] == sorted((r["mean_abs_effect"] for r in rows), reverse=True)
        for r in rows:
            assert_display(r["feature"], r["most_common_value"], r["most_common_value_display"])


def assert_display(feature: str, raw, display: str) -> None:
    """Display-ready factor values: rates in % with 1 decimal, counts as integers, days with 1 decimal,
    codes with their dictionary names."""
    assert isinstance(display, str) and display, (feature, raw)
    if raw is None:
        return
    if feature in ("hp_refusal_rate_prev",):
        assert re.fullmatch(r"\d+,\d%", display), (feature, raw, display)
    elif feature in (
        "queue_hp_prev_day",
        "day_of_window",
        "hp_n_hosp_prev",
        "hp_n_resolved_prev",
        "hosp_reg_7d",
        "hosp_reg_28d",
        "hosp_hosp_7d",
        "hosp_hosp_28d",
        "adm_refusals_28d",
    ):
        assert re.fullmatch(r"-?[\d ]+", display), (feature, raw, display)
    elif feature in ("hp_median_wait_prev", "ersb_avg_los"):
        assert re.fullmatch(r"[\d ]+,\d дн\.", display), (feature, raw, display)
    elif feature in ("org_code", "profile_code", "region_code", "hospital_region_code"):
        assert display.endswith(f"({raw})") and len(display) > len(str(raw)) + 3, (feature, raw, display)
    elif feature == "icd3":
        assert display.startswith(str(raw)) and len(display) > len(str(raw)) + 3, (feature, raw, display)
    elif feature == "registration_weekday":
        assert display in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"), (feature, raw, display)


@pytest.mark.parametrize("sort,key", [("risk", "pred_refusal_prob"), ("wait", "pred_wait_days")])
async def test_referrals_sorted_without_patient_identifiers(client, high_load, sort, key):
    org, profile = high_load["org_code"], high_load["profile_code"]
    body = await get_json(client, f"/hospitals/{org}/profiles/{profile}/referrals", sort=sort, limit=20)
    assert_page(body, 20)
    items = body["items"]
    assert items
    assert all(
        set(i)
        == {
            "hospitalization_code",
            "registration_date",
            "icd10_code",
            "referral_purpose",
            "pred_wait_days",
            "pred_refusal_prob",
            "is_high_risk",
            "explanation",
        }
        for i in items
    )
    values = [i[key] for i in items]
    assert values == sorted(values, reverse=True)
    for i in items:
        assert i["hospitalization_code"].split(".")[1:3] == [org, profile]
        assert set(i["explanation"]) == {"wait_time", "refusal_risk"}
        for factors in i["explanation"].values():
            for f in factors:
                assert {"feature", "value", "value_display", "effect", "text"} <= set(f)
                assert_display(f["feature"], f["value"], f["value_display"])
        assert "2025-03-01" <= i["registration_date"] <= "2025-03-31"
    assert (
        await client.get(f"{API}/hospitals/{org}/profiles/{profile}/referrals", params={"sort": "name"})
    ).status_code == 422


async def test_alerts(client):
    body = await get_json(client, "/alerts", limit=100)
    assert_page(body, 100)
    assert body["total"] > 0
    assert_ranked(body["items"])
    for item in body["items"]:
        assert item["reasons"] and all(isinstance(r, str) and r for r in item["reasons"])
        # the trend condition uses the excess trend (over the national median), not the raw one
        assert (item["load_index"] or 0) >= 70 or (item["queue_trend_4w"] or 0) >= 5


# ------------------------------------------------------------------------------------------ recommendations
async def test_recommendation_alternatives_same_region_and_profile(client):
    """Walk the highest-load rows until enough of them have alternatives; check every alternative
    independently against its own status card."""
    checked = 0
    alerts = await get_json(client, "/alerts", limit=60)
    for alert in alerts["items"]:
        org, profile = alert["org_code"], alert["profile_code"]
        body = await get_json(client, f"/hospitals/{org}/profiles/{profile}/recommendations")
        assert body["method"] == "historical_median"
        assert len(body["alternatives"]) <= body["rule"]["max_alternatives"]
        if not body["alternatives"]:
            assert body["reason"]
            continue
        assert body["eligible"] and body["current"]["in_region_top"]
        for alt in body["alternatives"]:
            assert alt["method"] == "historical_median" and alt["explanation"]
            assert alt["org_code"] != org
            assert alt["region_code"] == body["region_code"] and alt["profile_code"] == profile
            assert alt["delta_days"] >= body["rule"]["min_wait_delta_days"]
            assert alt["delta_days"] == pytest.approx(
                alt["expected_wait_current"] - alt["expected_wait_alternative"], abs=0.11
            )
            assert alt["backlog_days_alternative"] < alt["backlog_days_current"]
            # independent check: the alternative's own card says it is in the same region and profile
            card = await get_json(client, f"/hospitals/{alt['org_code']}/profiles/{profile}")
            assert card["status"]["region_code"] == body["region_code"]
            assert card["status"]["registrations_28d"] >= body["rule"]["min_registrations_28d"]
        checked += 1
        if checked >= 5:
            break
    assert checked >= 1, "no high-load hospital with alternatives among the first alerts"


async def test_recommendation_not_triggered_outside_region_top(client, high_load):
    hospitals = await get_json(client, f"/regions/{high_load['region_code']}/hospitals", limit=500)
    low = next(h for h in reversed(hospitals["items"]) if h["load_index"] is not None and not h["in_region_top"])
    body = await get_json(client, f"/hospitals/{low['org_code']}/profiles/{low['profile_code']}/recommendations")
    assert body["eligible"] is False and body["alternatives"] == [] and body["reason"]


# ------------------------------------------------------------------------------------------ decisions
async def test_decision_is_persisted_and_listed(client, high_load, created_decision_ids):
    recs = await get_json(
        client, f"/hospitals/{high_load['org_code']}/profiles/{high_load['profile_code']}/recommendations"
    )
    payload = {
        "region_code": high_load["region_code"],
        "org_code": high_load["org_code"],
        "profile_code": high_load["profile_code"],
        "recommendation_id": recs["alternatives"][0]["recommendation_id"] if recs["alternatives"] else None,
        "action": "defer",
        "comment": f"тест {uuid.uuid4()}",
        "actor": f"{TEST_ACTOR_PREFIX}{uuid.uuid4().hex[:8]}",
    }
    response = await client.post(f"{API}/decisions", json=payload)
    assert response.status_code == 201, response.text
    created = response.json()
    created_decision_ids.append(created["id"])
    assert {k: created[k] for k in payload} == payload and created["created_at"]

    listed = await get_json(client, "/decisions", org=payload["org_code"], profile=payload["profile_code"], limit=500)
    assert_page(listed, 500)
    match = [d for d in listed["items"] if d["id"] == created["id"]]
    assert match and {k: match[0][k] for k in payload} == payload
    assert all(
        d["org_code"] == payload["org_code"] and d["profile_code"] == payload["profile_code"] for d in listed["items"]
    )


async def test_invalid_decisions_are_rejected(client, high_load):
    base = {
        "region_code": high_load["region_code"],
        "org_code": high_load["org_code"],
        "profile_code": high_load["profile_code"],
        "action": "confirm",
        "actor": f"{TEST_ACTOR_PREFIX}invalid",
    }
    for bad in (
        {**base, "action": "approve"},
        {**base, "actor": ""},
        {**base, "region_code": "75" if base["region_code"] != "75" else "71"},
    ):
        response = await client.post(f"{API}/decisions", json=bad)
        assert response.status_code == 422, (bad, response.text)
    unknown_region = await client.post(f"{API}/decisions", json={**base, "region_code": "00"})
    assert unknown_region.status_code == 404


# ------------------------------------------------------------------------------------------ catalog
async def test_models(client):
    body = await get_json(client, "/models")
    assert [m["model_name"] for m in body] == ["wait_time", "refusal_risk", "load_forecast"]
    for m in body:
        assert m["version"] and m["title"] and m["headline"] and m["baselines"]
    assert body[2]["beats_baselines"] is True


async def test_dictionaries(client):
    body = await get_json(client, "/dictionaries")
    assert body["national_code"] == "KZ"
    assert len(body["regions"]) > 0 and all(r["code"] and r["name"] for r in body["regions"])
    assert len(body["profiles"]) > 0 and all(set(p) == {"code", "name", "is_day_hospital"} for p in body["profiles"])


# ------------------------------------------------------------------------------------------ latency
def largest_hospital_profile() -> tuple[str, str]:
    """The hospital × profile with the most test-period referrals (heaviest explanation aggregation)."""
    with SessionLocal() as session:
        return tuple(
            session.execute(
                text(
                    "SELECT org_code, profile_code FROM mart_hospital_profile_status "
                    "ORDER BY n_test_referrals DESC, org_code, profile_code LIMIT 1"
                )
            ).one()
        )


async def test_every_endpoint_under_500_ms(client, high_load, created_decision_ids):
    org, profile, region = high_load["org_code"], high_load["profile_code"], high_load["region_code"]
    big_org, big_profile = largest_hospital_profile()
    paths = [
        "/health",
        "/overview",
        f"/regions/{region}",
        f"/regions/{region}/hospitals?profile={profile}",
        f"/regions/{region}/hospitals",
        f"/hospitals/{org}/profiles/{profile}",
        f"/hospitals/{org}/profiles/{profile}/referrals?sort=risk&limit=50",
        f"/hospitals/{org}/profiles/{profile}/referrals?sort=wait&limit=50",
        f"/hospitals/{org}/profiles/{profile}/recommendations",
        f"/decisions?org={org}&profile={profile}",
        "/alerts",
        "/models",
        "/dictionaries",
        # the largest hospital × profile by referrals (08IV × DH on the full data: 1 400+ referrals)
        f"/hospitals/{big_org}/profiles/{big_profile}",
        f"/hospitals/{big_org}/profiles/{big_profile}/referrals?limit=100",
    ]
    slow = {}
    for path in paths:
        await client.get(f"{API}{path}")  # warm-up
        start = time.perf_counter()
        response = await client.get(f"{API}{path}")
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert response.status_code == 200, (path, response.text)
        if elapsed_ms >= 500:
            slow[path] = round(elapsed_ms)

    payload = {
        "region_code": region,
        "org_code": org,
        "profile_code": profile,
        "action": "confirm",
        "actor": f"{TEST_ACTOR_PREFIX}latency",
    }
    start = time.perf_counter()
    response = await client.post(f"{API}/decisions", json=payload)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert response.status_code == 201
    created_decision_ids.append(response.json()["id"])
    if elapsed_ms >= 500:
        slow["POST /decisions"] = round(elapsed_ms)
    assert not slow, f"endpoints over 500 ms: {slow}"
