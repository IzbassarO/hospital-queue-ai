"""Offline contract of the verification worklist: small synthetic rows, no database.

The properties this file exists to protect are the framing ones, because they are what a review list loses first:

  1. it is not a decision — `decision_owner` and the sentence that says so cannot be dropped or reworded away;
  2. it is not a queue — the order ranks the whole formal queue, so nothing is subtracted from it;
  3. the order is the source's own, published and dense, so "check the first N" means the same thing to everyone;
  4. the history-quality mark and the legacy rule's count agree with the rows they describe;
  5. the yield curve is hindsight, names the publication it read outcomes from, is measured against the whole
     queue's base rate, and no row carries an outcome.

The last section reads the published artifact itself (when present) and pins the canonical B5.1 evaluation.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.verification_worklist import VerificationWorklistBundle
from app.services.common import ValidationError
from app.services.verification_worklist import identity_of, parse_bundle

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verification_worklist_offline", ROOT / "tools/verification_worklist_bundle.py"
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)

COMMIT = "0" * 40
SHA = "a" * 64
PUBLISHED = (
    ROOT / "artifacts/verification_worklist/verification-worklist-origin-2025-03-17-v2/verification_worklist.json"
)


def item(
    referral_id: int = 1,
    rank: int = 1,
    *,
    waited: int = 45,
    horizon_probability: float = 0.02,
    score: float = 0.9,
    support: int = 80,
    reason: str | None = None,
    org_code: str = "H001",
) -> dict:
    return {
        "referral_id": referral_id,
        "rank": rank,
        "org_code": org_code,
        "region_code": "61",
        "profile_code": "021",
        "days_waited_at_origin": waited,
        "probability_admitted_30d": 0.0,
        "probability_admitted_horizon": horizon_probability,
        "probability_ever_admitted": horizon_probability,
        "observable_curve_end_day": 65.0,
        "estimate_tier": "hospital_profile",
        "verification_priority_score": score,
        "comparable_training_at_risk_rows": support,
        "history_quality_warning": reason is not None,
        "history_quality_reason_code": reason,
    }


def bundle_payload(items: list[dict], **overrides) -> dict:
    formal = len(items)
    warnings: dict[str, int] = {}
    for row in items:
        if row["history_quality_reason_code"]:
            warnings[row["history_quality_reason_code"]] = warnings.get(row["history_quality_reason_code"], 0) + 1
    warned = sum(warnings.values())
    selected = sum(row["days_waited_at_origin"] >= 30 and row["probability_admitted_horizon"] < 0.1 for row in items)
    area = {
        "formal_queue_count": formal,
        "history_quality_warning_count": warned,
        "history_quality_warning_share": warned / formal,
    }
    found = formal // 2
    payload = {
        "schema_version": "verification_worklist_v2",
        "contract_version": "2.0.0",
        "publication_id": "test-verification-worklist",
        "publication_identity_sha256": "0" * 64,
        "source_code_commit": COMMIT,
        "origin": "2025-03-17",
        "decision_owner": "SPECIALIST_DECIDES",
        "not_a_decision": {"ru": "Решение принимает специалист.", "kk": "Шешімді маман қабылдайды."},
        "source_publication": {
            "publication_id": "ghost-queue-2025-03-17-v2",
            "publication_identity_sha256": SHA,
            "file_sha256": SHA,
            "schema_version": 2,
            "model": "origin-safe hierarchical Aalen-Johansen",
        },
        "ranking": {
            "definition": {"ru": "сначала с большим приоритетом", "kk": "алдымен басымдығы жоғарылар"},
            "keys": ["origin_safe_verification_priority desc", "days_waited_at_origin_desc"],
            "score_name": "origin_safe_verification_priority",
            "score_formula": "one_minus_p_admit_90d_x_wait_maturity_x_at_risk_support",
            "wait_maturity_days": 30,
            "minimum_comparable_at_risk_rows": 50,
            "training_only_justification": "fixed before any hindsight",
        },
        "legacy_rule": {
            "role": "AUDITED_REFERENCE_ONLY",
            "reason_code": "waited_30d_and_p_admit_90d_below_0_10",
            "minimum_days_waited": 30,
            "horizon_days": 90,
            "probability_strictly_below": 0.1,
            "selected_count": selected,
            "training_only_justification": "fixed before any hindsight",
            "statement": {"ru": "прежнее правило, только для сравнения", "kk": "бұрынғы ереже, тек салыстыру үшін"},
        },
        "history_quality": {
            "definition": {"ru": "мало сопоставимой истории", "kk": "салыстырмалы тарих аз"},
            "warning_count": warned,
            "warning_share": warned / formal,
            "reason_counts": warnings or {"insufficient_comparable_history": 0},
        },
        "estimands": {"conditioning": "conditional on remaining unresolved"},
        "counts": {"formal_queue_count": formal, "ranked_count": formal},
        "yield_curve": {
            "disclosure": "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
            "definition": {"ru": "ретроспективная проверка", "kk": "ретроспективті тексеру"},
            "outcome_source": "waiting-list-origin-2025-03-17-v1",
            "outcome_source_identity_sha256": SHA,
            "base": {"evaluated": formal, "no_longer_current": found, "share": found / formal},
            "points": [
                {"checked": formal, "no_longer_current": found, "share": found / formal, "lift": 1.0 if found else 0.0}
            ],
        },
        "areas": [
            {"level": "region", "code": "61", "region_code": None, **area},
            {"level": "hospital", "code": "H001", "region_code": "61", **area},
        ],
        "generated_at": "2026-09-28T00:00:00+00:00",
        "limitations": ["a review list, not a queue"],
        "items": items,
    }
    payload.update(overrides)
    return payload


def two() -> list[dict]:
    return [item(1, 1, score=0.9), item(2, 2, score=0.5, support=10, reason="insufficient_comparable_history")]


def validated(payload: dict) -> VerificationWorklistBundle:
    bundle = VerificationWorklistBundle.model_validate(payload)
    body = bundle.model_dump(mode="json")
    body["publication_identity_sha256"] = identity_of(bundle)
    return VerificationWorklistBundle.model_validate(body)


def refused(payload: dict, match: str | None = None) -> None:
    with pytest.raises(PydanticValidationError, match=match):
        VerificationWorklistBundle.model_validate(payload)


# ------------------------------------------------------------------------------- it is not a decision


def test_the_publication_must_say_who_decides() -> None:
    payload = bundle_payload(two())
    for missing in ("decision_owner", "not_a_decision"):
        refused({key: value for key, value in payload.items() if key != missing})


def test_every_sentence_the_screen_shows_is_published_in_both_languages() -> None:
    """A framing sentence a Kazakh-speaking reader cannot read is not framing."""
    bundle = validated(bundle_payload(two()))
    for sentence in (
        bundle.not_a_decision,
        bundle.legacy_rule.statement,
        bundle.ranking.definition,
        bundle.history_quality.definition,
        bundle.yield_curve.definition,
    ):
        assert sentence.ru.strip() and sentence.kk.strip()
        assert sentence.ru != sentence.kk, "a language is missing its own wording"


def test_a_sentence_with_only_one_language_is_refused() -> None:
    payload = bundle_payload(two())
    payload["not_a_decision"] = {"ru": "Решение принимает специалист."}
    refused(payload)


def test_the_decision_owner_is_a_fixed_literal_not_free_text() -> None:
    refused(bundle_payload(two(), decision_owner="SYSTEM_DECIDES"))


# ------------------------------------------------------------------------------- it is not a queue


def test_the_order_ranks_the_whole_formal_queue_and_subtracts_nothing() -> None:
    payload = bundle_payload(two())
    payload["counts"] = {"formal_queue_count": 3, "ranked_count": 2}
    refused(payload, "whole formal queue")


def test_the_region_rows_must_account_for_the_whole_queue() -> None:
    payload = bundle_payload(two())
    payload["areas"][0]["formal_queue_count"] = 5
    payload["areas"][0]["history_quality_warning_share"] = 0.2
    refused(payload, "region rows do not sum")


def test_an_area_share_that_disagrees_with_its_counts_is_refused() -> None:
    payload = bundle_payload(two())
    payload["areas"][1]["history_quality_warning_share"] = 0.99
    refused(payload, "history_quality_warning_share")


def test_a_row_carrying_an_outcome_is_refused() -> None:
    """Origin-time rows only: a hindsight field has no place on a row, whatever it is called."""
    for field, value in (("observed_after_origin", {"status": "REFUSED"}), ("status", "ADMITTED"), ("is_ghost", True)):
        rows = two()
        rows[0][field] = value
        refused(bundle_payload(rows), "Extra inputs are not permitted")


# ------------------------------------------------------------------------------- the order and the marks


def test_rank_is_a_dense_sequence_so_first_n_means_one_thing() -> None:
    rows = two()
    rows[1]["rank"] = 3
    refused(bundle_payload(rows), "dense 1..n")


def test_a_higher_priority_may_not_be_ranked_below_a_lower_one() -> None:
    rows = two()
    rows[0]["verification_priority_score"], rows[1]["verification_priority_score"] = 0.5, 0.9
    refused(bundle_payload(rows), "higher priority score")


def test_a_warning_needs_exactly_one_reason() -> None:
    rows = two()
    rows[1]["history_quality_reason_code"] = None
    refused(bundle_payload(rows), "exactly one reason")


def test_an_insufficient_history_code_must_agree_with_the_rows_support() -> None:
    rows = two()
    rows[1]["comparable_training_at_risk_rows"] = 80
    refused(bundle_payload(rows), "disagrees with its support")


def test_the_history_quality_counts_must_match_the_rows() -> None:
    payload = bundle_payload(two())
    payload["history_quality"]["reason_counts"] = {
        "insufficient_comparable_history": 1,
        "degenerate_conditional_distribution": 1,
    }
    payload["history_quality"]["warning_count"] = 2
    payload["history_quality"]["warning_share"] = 1.0
    refused(payload, "reason_counts does not match")


def test_the_legacy_rule_count_must_match_the_rows() -> None:
    payload = bundle_payload(two())
    payload["legacy_rule"]["selected_count"] = 0
    refused(payload, "selected_count")


def test_the_legacy_count_tolerates_only_the_published_rounding_at_the_threshold() -> None:
    """The source counts on unrounded probabilities; a row published as 0.1 may have been 0.0999999."""
    rows = [item(1, 1, horizon_probability=0.1)]
    validated(bundle_payload(rows, legacy_rule={**bundle_payload(rows)["legacy_rule"], "selected_count": 1}))
    rows = [item(1, 1, horizon_probability=0.1001)]
    refused(
        bundle_payload(rows, legacy_rule={**bundle_payload(rows)["legacy_rule"], "selected_count": 1}), "selected_count"
    )


# ------------------------------------------------------------------------------- the yield curve


def test_the_yield_curve_is_marked_as_hindsight_and_names_its_source() -> None:
    bundle = validated(bundle_payload(two()))
    assert bundle.yield_curve.disclosure == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
    assert bundle.yield_curve.outcome_source.startswith("waiting-list-")


def test_a_yield_point_may_not_find_more_than_it_checked() -> None:
    payload = bundle_payload(two())
    payload["yield_curve"]["points"] = [{"checked": 2, "no_longer_current": 3, "share": 1.5, "lift": 3.0}]
    refused(payload)


def test_a_lift_that_disagrees_with_the_base_is_refused() -> None:
    payload = bundle_payload(two())
    payload["yield_curve"]["points"][0]["lift"] = 1.3
    refused(payload, "lift does not match")


def test_the_base_is_the_whole_formal_queue() -> None:
    payload = bundle_payload(two())
    payload["yield_curve"]["base"] = {"evaluated": 1, "no_longer_current": 0, "share": 0.0}
    payload["yield_curve"]["points"][0]["lift"] = 0.0
    refused(payload, "whole formal queue")


def test_the_curve_may_not_check_more_referrals_than_the_list_holds() -> None:
    payload = bundle_payload(two())
    payload["yield_curve"]["points"] = [{"checked": 50, "no_longer_current": 25, "share": 0.5, "lift": 1.0}]
    refused(payload, "checks more referrals")


# ------------------------------------------------------------------------------- identity


def test_identity_covers_the_content_and_ignores_the_generation_time() -> None:
    bundle = validated(bundle_payload(two()))
    raw = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert parse_bundle(raw.encode()).bundle.publication_identity_sha256 == bundle.publication_identity_sha256
    later = bundle.model_dump(mode="json")
    later["generated_at"] = "2027-01-01T00:00:00+00:00"
    again = json.dumps(later, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert parse_bundle(again.encode()).bundle.publication_identity_sha256 == bundle.publication_identity_sha256


def test_rewording_the_framing_changes_the_identity() -> None:
    """The sentence about who decides is part of what was published, not skin."""
    reworded = validated(bundle_payload(two())).model_dump(mode="json")
    reworded["not_a_decision"] = {"ru": "Система решает сама.", "kk": "Жүйе өзі шешеді."}
    raw = json.dumps(reworded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValidationError, match="does not match canonical content"):
        parse_bundle(raw.encode())


# ------------------------------------------------------------------------------- the builder's own rules


def _source_row(referral_id: int, rank: int, score: float = 0.5) -> dict:
    return {
        "referral_id": referral_id,
        "verification_rank": rank,
        "verification_priority_score": score,
        "org_code": "H001",
        "hospital_region_code": "61",
        "profile_code": "021",
        "days_waited_at_origin": 40,
        "probability_admitted_within_30d": 0.0,
        "probability_admitted_within_90d": 0.05,
        "probability_ever_admitted_within_observable_curve": 0.05,
        "observable_curve_end_day": 65.0,
        "estimate_tier": "hospital_profile",
        "comparable_training_at_risk_rows": 80,
        "history_quality_warning": False,
        "history_quality_reason_code": None,
    }


def _write_source(path: Path, payload: dict) -> Path:
    path.write_bytes(gzip.compress(json.dumps(payload).encode()))
    return path


def test_only_the_final_source_schema_is_read(tmp_path: Path) -> None:
    """The previous ghost-queue schema is refused rather than silently published from."""
    for version in (1, 99):
        path = _write_source(tmp_path / f"ghost-queue-{version}.json.gz", {"schema_version": version})
        with pytest.raises(SystemExit, match="schema_version"):
            builder.read_source(path)


def test_the_default_build_refuses_bytes_other_than_the_pinned_b51_publication() -> None:
    with pytest.raises(SystemExit, match="not the pinned B5.1"):
        builder.require_pinned({"publication_identity_sha256": builder.SOURCE_IDENTITY_SHA256}, SHA)
    with pytest.raises(SystemExit, match="not the pinned B5.1"):
        builder.require_pinned({"publication_identity_sha256": SHA}, builder.SOURCE_FILE_SHA256)
    builder.require_pinned({"publication_identity_sha256": builder.SOURCE_IDENTITY_SHA256}, builder.SOURCE_FILE_SHA256)


def test_the_builder_keeps_the_sources_own_rank_and_never_reranks() -> None:
    source = {"referrals": [_source_row(55525, 2), _source_row(476650, 1), _source_row(7, 3)]}
    ranked = builder.ranked_items(source)
    assert [row["referral_id"] for row in ranked] == [476650, 55525, 7]
    assert [row["rank"] for row in ranked] == [1, 2, 3]


def test_the_builder_refuses_a_source_rank_with_gaps() -> None:
    with pytest.raises(SystemExit, match="dense"):
        builder.ranked_items({"referrals": [_source_row(1, 1), _source_row(2, 3)]})


def test_the_yield_curve_counts_non_admissions_in_order_against_the_base(tmp_path: Path) -> None:
    outcomes = {1: "REFUSED", 2: "ADMITTED", 3: "STILL_WAITING_AT_CUTOFF", 4: "ADMITTED"}
    waiting = tmp_path / "waiting_list.json"
    waiting.write_text(
        json.dumps(
            {
                "publication_id": "waiting-list-test",
                "publication_identity_sha256": SHA,
                "referrals": [
                    {"referral_id": key, "observed_after_origin": {"status": value}} for key, value in outcomes.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    items = [{"referral_id": key} for key in (1, 3, 2, 4)]
    curve = builder.yield_curve(items, waiting, legacy_count=2)
    assert curve["disclosure"] == "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN"
    assert curve["base"] == {"evaluated": 4, "no_longer_current": 2, "share": 0.5}
    assert curve["points"] == [{"checked": 2, "no_longer_current": 2, "share": 1.0, "lift": 2.0}]


# ------------------------------------------------------------------------------- the published artifact


@pytest.fixture(scope="module")
def published() -> dict:
    if not PUBLISHED.is_file():
        pytest.skip("the published verification worklist is not built here (make verification-worklist-bundle)")
    return json.loads(PUBLISHED.read_text(encoding="utf-8"))


def test_the_publication_is_built_from_the_final_b51_source(published: dict) -> None:
    source = published["source_publication"]
    assert source["publication_id"] == "ghost-queue-2025-03-17-v2"
    assert source["schema_version"] == 2
    assert source["publication_identity_sha256"] == builder.SOURCE_IDENTITY_SHA256
    assert source["file_sha256"] == builder.SOURCE_FILE_SHA256
    assert parse_bundle(PUBLISHED.read_bytes()).bundle.publication_id == "verification-worklist-origin-2025-03-17-v2"


def test_the_publication_carries_the_canonical_b51_evaluation(published: dict) -> None:
    curve = published["yield_curve"]
    assert curve["base"] == {"evaluated": 65232, "no_longer_current": 19769, "share": pytest.approx(0.303, abs=5e-4)}
    points = {point["checked"]: point for point in curve["points"]}
    canonical = {500: (159, 0.318, 1.05), 1000: (298, 0.298, 0.98), 2000: (768, 0.384, 1.27), 5000: (2040, 0.408, 1.35)}
    canonical[13328] = (4842, 0.363, 1.20)
    assert sorted(points) == sorted(canonical)
    for checked, (found, share, lift) in canonical.items():
        assert points[checked]["no_longer_current"] == found
        assert points[checked]["share"] == pytest.approx(share, abs=5e-4)
        assert points[checked]["lift"] == pytest.approx(lift, abs=5e-3)


def test_the_publication_keeps_the_formal_queue_whole_and_the_history_warning(published: dict) -> None:
    assert published["counts"] == {"formal_queue_count": 65232, "ranked_count": 65232}
    assert len(published["items"]) == 65232
    quality = published["history_quality"]
    assert quality["warning_count"] == 19950
    assert quality["warning_share"] == pytest.approx(0.306, abs=5e-4)
    assert quality["reason_counts"] == {
        "insufficient_comparable_history": 10895,
        "insufficient_and_degenerate_comparable_history": 6463,
        "degenerate_conditional_distribution": 2592,
    }
    assert published["legacy_rule"]["selected_count"] == 13328


def test_no_published_row_carries_a_hindsight_label(published: dict) -> None:
    origin_time = set(item())
    assert all(set(row) == origin_time for row in published["items"])
