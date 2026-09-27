"""Dictionary rules of the ingest layer (docs/data.md §3) that do not need the raw data.

Covered: the manual override file for hospital <-> ERSB matching (`load_org_overrides`, pure: validation of unknown
codes and contradictory entries), the KATO reference list, the regions.yaml reader, and `build_dim_region` on a
handful of staged rows in an in-process DuckDB connection, which is where the alias lookup, the referral-weighted vote,
the ambiguity flag and manual overrides are decided."""

from __future__ import annotations

import datetime as dt

import duckdb
import pytest
import yaml

from hqai_ml.ingest.config import IngestParams
from hqai_ml.ingest.dictionaries import KATO_REFERENCE, _load_regions_yaml, build_dim_region, load_org_overrides
from hqai_ml.ingest.normalize import name_key


# ------------------------------------------------------------ load_org_overrides
def write_yaml(path, data) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


ORGS = {"028V", "0286"}
ERSB_IDS = {792, 123}


def test_missing_overrides_file_means_no_overrides(tmp_path):
    assert load_org_overrides(tmp_path / "org_matches.yaml", ORGS, ERSB_IDS) == {"accept": {}, "reject": {}}


def test_empty_overrides_file_means_no_overrides(tmp_path):
    path = tmp_path / "org_matches.yaml"
    path.write_text("# comments only\n", encoding="utf-8")
    assert load_org_overrides(path, ORGS, ERSB_IDS) == {"accept": {}, "reject": {}}


def test_accept_and_reject_entries_are_read_with_their_notes(tmp_path):
    """§3 manual overrides: accept maps org_code -> (ersb_id, note); reject keys the forbidden pair."""
    path = tmp_path / "org_matches.yaml"
    write_yaml(
        path,
        {
            "accept": [{"org_code": "028V", "ersb_id": 792, "note": "same clinic"}],
            "reject": [{"org_code": "0286", "ersb_id": 123}],
        },
    )
    assert load_org_overrides(path, ORGS, ERSB_IDS) == {
        "accept": {"028V": (792, "same clinic")},
        "reject": {("0286", 123): ""},
    }


def test_unknown_org_code_stops_the_run(tmp_path):
    """§3 validation: the run stops if an org_code does not exist."""
    path = tmp_path / "org_matches.yaml"
    write_yaml(path, {"accept": [{"org_code": "ZZZZ", "ersb_id": 792}]})
    with pytest.raises(ValueError, match="accept: unknown org_code 'ZZZZ'"):
        load_org_overrides(path, ORGS, ERSB_IDS)


def test_unknown_ersb_id_stops_the_run(tmp_path):
    """§3 validation: the run stops if an ersb_id does not exist."""
    path = tmp_path / "org_matches.yaml"
    write_yaml(path, {"reject": [{"org_code": "028V", "ersb_id": 999}]})
    with pytest.raises(ValueError, match=r"reject: unknown ersb_id 999 \(org_code 028V\)"):
        load_org_overrides(path, ORGS, ERSB_IDS)


def test_unquoted_numeric_org_code_is_compared_as_text_and_reported(tmp_path):
    """§3: `org_code` must be quoted in YAML; an unquoted number (0123 -> 83 octal, 286 -> 286) matches no code."""
    path = tmp_path / "org_matches.yaml"
    entries = "accept:\n  - {org_code: 0123, ersb_id: 792}\n  - {org_code: 286, ersb_id: 792}\n"
    path.write_text(entries, encoding="utf-8")
    with pytest.raises(ValueError, match="unknown org_code '83'.*unknown org_code '286'"):
        load_org_overrides(path, ORGS | {"0123"}, ERSB_IDS)


def test_ersb_id_must_be_an_integer(tmp_path):
    path = tmp_path / "org_matches.yaml"
    write_yaml(path, {"accept": [{"org_code": "028V", "ersb_id": "792"}]})
    with pytest.raises(ValueError, match="unknown ersb_id '792'"):
        load_org_overrides(path, ORGS, ERSB_IDS)


def test_one_org_code_accepted_for_two_ersb_rows_stops_the_run(tmp_path):
    """§3 validation: one org_code accepted for two different ERSB rows is contradictory."""
    path = tmp_path / "org_matches.yaml"
    write_yaml(path, {"accept": [{"org_code": "028V", "ersb_id": 792}, {"org_code": "028V", "ersb_id": 123}]})
    with pytest.raises(ValueError, match="accepted for two different ersb_ids"):
        load_org_overrides(path, ORGS, ERSB_IDS)


def test_same_org_code_accepted_twice_for_the_same_row_is_allowed(tmp_path):
    path = tmp_path / "org_matches.yaml"
    write_yaml(path, {"accept": [{"org_code": "028V", "ersb_id": 792}, {"org_code": "028V", "ersb_id": 792}]})
    assert load_org_overrides(path, ORGS, ERSB_IDS)["accept"] == {"028V": (792, "")}


def test_pair_both_accepted_and_rejected_stops_the_run(tmp_path):
    """§3 validation: the same pair cannot be both accepted and rejected."""
    path = tmp_path / "org_matches.yaml"
    pair = {"org_code": "028V", "ersb_id": 792}
    write_yaml(path, {"accept": [pair], "reject": [pair]})
    with pytest.raises(ValueError, match="028V -> 792 is both accepted and rejected"):
        load_org_overrides(path, ORGS, ERSB_IDS)


def test_all_errors_are_reported_together_with_the_file_name(tmp_path):
    path = tmp_path / "org_matches.yaml"
    write_yaml(path, {"accept": [{"org_code": "A", "ersb_id": 1}], "reject": [{"org_code": "B", "ersb_id": 2}]})
    with pytest.raises(ValueError) as info:
        load_org_overrides(path, ORGS, ERSB_IDS)
    message = str(info.value)
    assert message.startswith(str(path))
    assert message.count("unknown org_code") == 2 and message.count("unknown ersb_id") == 2


# ------------------------------------------------------------------ dim_region
def test_kato_reference_lists_twenty_distinct_regions():
    """§3 dim_region: 20 codes, consistent with the KATO classifier (a hint for review, not used by the pipeline)."""
    assert len(KATO_REFERENCE) == 20
    assert len(set(KATO_REFERENCE.values())) == 20
    assert all(len(code) == 2 and code.isdigit() for code in KATO_REFERENCE)


def test_load_regions_yaml_keys_are_strings_and_missing_file_is_empty(tmp_path):
    """regions.yaml codes like '10' must stay strings even if written unquoted."""
    assert _load_regions_yaml(tmp_path / "regions.yaml") == {}
    path = tmp_path / "regions.yaml"
    path.write_text("min_share: 0.8\nregions:\n  10: {name: A}\n  '11': {name: B}\n", encoding="utf-8")
    assert _load_regions_yaml(path) == {"10": {"name": "A"}, "11": {"name": "B"}}
    path.write_text("min_share: 0.8\n", encoding="utf-8")
    assert _load_regions_yaml(path) == {}


PARAMS = IngestParams(
    window_start=dt.date(2025, 1, 1),
    window_end=dt.date(2025, 3, 31),
    planned_dt_min=dt.date(2024, 6, 1),
    planned_dt_max=dt.date(2026, 6, 30),
    region_vote_min_share=0.8,
    fuzzy_min_score=90,
    fuzzy_min_sort_score=90,
    day_hospital_code="DH",
    day_hospital_name="Дневной стационар",
)


def _staged_region_inputs(con: duckdb.DuckDBPyConnection, referrals: list[tuple[str, str, int]]) -> None:
    """stg_referral rows as (region_code, hospital_key, n) and a fixed dataset-3 hospital -> region table."""
    con.execute("CREATE TABLE stg_referral (region_code VARCHAR, hospital_key VARCHAR)")
    con.executemany(
        "INSERT INTO stg_referral SELECT ?, ? FROM range(?)", [[code, key, n] for code, key, n in referrals]
    )
    con.execute("CREATE TABLE stg_refusal (org_in_key VARCHAR, region_in VARCHAR)")
    con.executemany(
        "INSERT INTO stg_refusal VALUES (?, ?)",
        [
            ["больница а", "Алматинская область"],
            ["больница а", "Алматинская область"],
            ["больница а", "г. Алматы"],
            ["больница б", "г. Алматы"],
        ],
    )


@pytest.fixture
def con():
    connection = duckdb.connect()
    yield connection
    connection.close()


def test_dim_region_vote_is_weighted_by_referrals_and_alias_lookup_uses_name_keys(con, tmp_path):
    """§3 dim_region: referral-weighted majority vote; region_lookup holds name_key of the name and of every alias."""
    _staged_region_inputs(con, [("19", "больница а", 90), ("19", "больница б", 10), ("75", "больница б", 5)])
    regions_yaml = tmp_path / "regions.yaml"
    write_yaml(regions_yaml, {"regions": {"19": {"aliases": ["Алматинская обл."]}}})
    stats = build_dim_region(con, PARAMS, regions_yaml, waiting_codes=["19", "75"])

    rows = con.execute(
        "SELECT region_code, region_name, vote_share, vote_referrals, runner_up_name, is_ambiguous, manual_override "
        "FROM dim_region ORDER BY region_code"
    ).fetchall()
    assert rows == [
        ("19", "Алматинская область", 0.9, 100, "г. Алматы", False, False),
        ("75", "г. Алматы", 1.0, 5, None, False, False),
    ]
    lookup = dict(con.execute("SELECT key, region_code FROM region_lookup").fetchall())
    assert lookup == {
        name_key("Алматинская область"): "19",
        name_key("Алматинская обл."): "19",
        name_key("г. Алматы"): "75",
    }
    assert lookup["алматинская обл"] == "19"
    assert stats == {"codes": 2, "ambiguous": [], "manual_overrides": [], "name_collisions": []}

    written = yaml.safe_load(regions_yaml.read_text(encoding="utf-8"))
    assert written["min_share"] == 0.8
    assert written["regions"]["19"]["aliases"] == ["Алматинская обл."]
    assert written["regions"]["19"]["kato_reference"] == "Алматинская область"
    assert written["regions"]["19"]["vote"] == {
        "name": "Алматинская область",
        "share": 0.9,
        "referrals_voted": 100,
        "runner_up": "г. Алматы",
        "runner_up_share": 0.1,
    }


def test_dim_region_flags_ambiguous_codes_and_keeps_unvoted_codes(con, tmp_path):
    """§3 dim_region: is_ambiguous when the winner's share < region_vote_min_share; a code without referrals stays
    in the table with a placeholder name so the mapping can be fixed by hand."""
    _staged_region_inputs(con, [("19", "больница а", 6), ("19", "больница б", 4)])
    regions_yaml = tmp_path / "regions.yaml"
    stats = build_dim_region(con, PARAMS, regions_yaml, waiting_codes=["19", "71"])
    rows = dict(con.execute("SELECT region_code, (region_name, is_ambiguous) FROM dim_region").fetchall())
    assert rows == {"19": ("Алматинская область", True), "71": ("(unknown region 71)", True)}
    assert stats["ambiguous"] == ["19", "71"]
    written = yaml.safe_load(regions_yaml.read_text(encoding="utf-8"))
    assert written["regions"]["71"]["vote"] == {
        "name": None,
        "share": None,
        "referrals_voted": 0,
        "runner_up": None,
        "runner_up_share": None,
    }


def test_dim_region_manual_override_wins_over_the_vote_and_survives_the_rewrite(con, tmp_path):
    """§3 dim_region: `name` + `manual_override: true` in regions.yaml pins the name; the next run keeps it and the
    lookup maps the pinned name, not the vote winner."""
    _staged_region_inputs(con, [("19", "больница б", 10)])
    regions_yaml = tmp_path / "regions.yaml"
    write_yaml(regions_yaml, {"regions": {"19": {"name": "Алматинская область", "manual_override": True}}})
    stats = build_dim_region(con, PARAMS, regions_yaml, waiting_codes=["19"])
    row = con.execute("SELECT region_name, vote_region_name, manual_override FROM dim_region").fetchone()
    assert row == ("Алматинская область", "г. Алматы", True)
    assert stats["manual_overrides"] == ["19"]
    assert dict(con.execute("SELECT key, region_code FROM region_lookup").fetchall()) == {"алматинская область": "19"}
    written = yaml.safe_load(regions_yaml.read_text(encoding="utf-8"))
    assert written["regions"]["19"]["manual_override"] is True
    assert written["regions"]["19"]["name"] == "Алматинская область"
    assert written["regions"]["19"]["vote"]["name"] == "г. Алматы"


def test_dim_region_reports_alias_collisions_between_codes(con, tmp_path):
    """§3 dim_region: an alias whose name_key already belongs to another code is reported as a collision."""
    _staged_region_inputs(con, [("19", "больница а", 10), ("75", "больница б", 10)])
    regions_yaml = tmp_path / "regions.yaml"
    write_yaml(regions_yaml, {"regions": {"19": {"aliases": ["Г. АЛМАТЫ"]}}})
    stats = build_dim_region(con, PARAMS, regions_yaml, waiting_codes=["19", "75"])
    assert stats["name_collisions"] == ["г алматы"]
    assert con.execute("SELECT count(*) FROM region_lookup WHERE key = 'г алматы'").fetchone()[0] == 1
