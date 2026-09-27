"""When the demo seed may touch a database that is not empty.

`make demo` is the first command a reviewer runs, and it may meet three kinds of database: an empty one (load the
seed), one that already carries the seed (leave it alone), and one built by the full pipeline, which holds more
than the seed because the seed's referral-level tables are a two-region slice (leave it alone as well and only
publish the evidence). Anything else — a table with fewer rows than the seed — is partial or damaged data and must
stop the load rather than be silently overwritten. These are pure-function tests; no database is needed.
"""

from app.services.seed import holds_more_than_seed

ENTRIES = [
    {"table": "dim_region", "rows": 20},
    {"table": "dim_profile", "rows": 97},
    {"table": "fact_referral", "rows": 19_698},
    {"table": "mart_area_status", "rows": 21},
]


def counts(**overrides: int) -> dict[str, int]:
    """Row counts equal to the seed, with the named tables overridden."""
    return {entry["table"]: overrides.get(entry["table"], entry["rows"]) for entry in ENTRIES}


def test_a_full_pipeline_database_is_left_alone():
    """The real case: national facts (767 130 referrals) against the seed's two-region slice."""
    assert holds_more_than_seed(counts(fact_referral=767_130), ENTRIES) is True


def test_one_extra_row_is_enough_to_count_as_richer():
    assert holds_more_than_seed(counts(dim_region=21), ENTRIES) is True


def test_an_identical_database_is_not_richer():
    """Equal counts are handled earlier by the identity check; this function must not claim them as a superset."""
    assert holds_more_than_seed(counts(), ENTRIES) is False


def test_an_empty_database_is_not_richer():
    assert holds_more_than_seed({entry["table"]: 0 for entry in ENTRIES}, ENTRIES) is False


def test_a_partially_filled_table_stops_the_load():
    """Fewer rows than the seed means damaged or half-loaded data: refuse instead of overwriting."""
    assert holds_more_than_seed(counts(mart_area_status=3), ENTRIES) is False


def test_richer_and_poorer_together_stop_the_load():
    """A database that is ahead in one table and behind in another is inconsistent, not a superset."""
    assert holds_more_than_seed(counts(fact_referral=767_130, mart_area_status=3), ENTRIES) is False


def test_an_empty_table_beside_richer_ones_is_still_a_superset():
    """A zero-row table is 'not loaded yet', not 'partially loaded': the publications can still be added."""
    assert holds_more_than_seed(counts(fact_referral=767_130, mart_area_status=0), ENTRIES) is True
