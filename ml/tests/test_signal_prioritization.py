from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from hqai_ml.flow_forecast.config import SignalPrioritizationConfig
from hqai_ml.flow_forecast.pressure import ENTITY_ORIGIN_ALERT_UNIT
from hqai_ml.flow_forecast.prioritization import (
    _require_source_contract,
    assert_displayed_evidence_consistency,
    inbox_views,
    materiality_diagnostics,
    observed_anomaly_view,
    prepare_inbox,
    regional_rollup,
)


def config(**updates) -> SignalPrioritizationConfig:
    raw = {
        "schema_version": 1,
        "version": "signals-inbox-v1",
        "seed": 42,
        "source_signal_contract_version": "preventive-flow-pressure-v1",
        "source_alert_unit": ENTITY_ORIGIN_ALERT_UNIT,
        "primary_target": "registrations",
        "secondary_target": "cohort_hospitalizations",
        "materiality_floor_expected_count": 1.0,
        "alert_severities": ["HIGH", "ELEVATED", "WATCH"],
        "ranking_order": [
            "severity_desc",
            "lead_time_days_asc",
            "direct_supported_first",
            "calibrated_uncertainty_first",
            "valid_central_threshold_ratio_desc",
            "region_id_asc",
            "hospital_id_asc",
            "profile_id_asc",
            "series_id_asc",
        ],
        "demo_top_n": 20,
        "regional_top_profiles": 5,
        "human_review_required": True,
        "autonomous_action": False,
        "automatic_promotion": False,
        "identity_sha256": "config",
    }
    raw.update(updates)
    return SignalPrioritizationConfig(**raw)


def entity_row(
    hospital_id: str,
    severity: str,
    lead: int = 1,
    *,
    profile_id: str = "p1",
    region_id: str = "r1",
    target: str = "registrations",
    direct: bool = True,
    calibrated: bool = True,
    threshold: float = 10.0,
    forecast: float | None = None,
) -> dict:
    origin = pd.Timestamp("2025-03-17")
    values = {
        "HIGH": (12.0, 11.0, 13.0, "CALIBRATED_LOWER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"),
        "ELEVATED": (12.0, 9.0, 13.0, "CENTRAL_FORECAST_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"),
        "WATCH": (9.0, 8.0, 11.0, "CALIBRATED_UPPER_EXCEEDS_HISTORICAL_FLOW_THRESHOLD"),
        "NORMAL": (9.0, 8.0, 10.0, "FORECAST_BELOW_HISTORICAL_FLOW_THRESHOLD"),
        "UNSUPPORTED": (9.0, np.nan, np.nan, "THRESHOLD_UNSUPPORTED"),
    }
    default_forecast, lower, upper, reason = values[severity]
    forecast = default_forecast if forecast is None else forecast
    unsupported = severity == "UNSUPPORTED"
    if not calibrated:
        lower = np.nan
        upper = np.nan
        if severity in {"HIGH", "WATCH"}:
            raise ValueError("HIGH/WATCH fixture requires calibrated interval evidence")
    series_id = f"hp:{hospital_id}:{profile_id}"
    return {
        "phase": "final_test",
        "origin": origin,
        "target": target,
        "series_id": series_id,
        "signal_id": f"signal-{series_id}-{target}",
        "signal_type": "preventive_flow_pressure",
        "alert_unit": ENTITY_ORIGIN_ALERT_UNIT,
        "severity": severity,
        "max_severity_7d": severity,
        "max_severity_14d": severity,
        "displayed_severity_basis": "max_severity_14d",
        "severity_evidence_horizon": lead,
        "severity_evidence_date": origin + pd.Timedelta(days=lead),
        "hospital_id": hospital_id,
        "region_id": region_id,
        "profile_id": profile_id,
        "forecast_origin": origin,
        "first_crossing_date": origin + pd.Timedelta(days=lead)
        if severity not in {"NORMAL", "UNSUPPORTED"}
        else pd.NaT,
        "lead_time_days": lead if severity not in {"NORMAL", "UNSUPPORTED"} else np.nan,
        "first_crossing_severity": severity if severity not in {"NORMAL", "UNSUPPORTED"} else None,
        "any_alert_7d": severity not in {"NORMAL", "UNSUPPORTED"} and lead <= 7,
        "any_alert_14d": severity not in {"NORMAL", "UNSUPPORTED"} and lead <= 14,
        "forecast_value": forecast,
        "threshold_value": np.nan if unsupported else threshold,
        "uncertainty_lower": lower,
        "uncertainty_upper": upper,
        "forecast_source": "direct_quantile_ml" if direct else "regional_fallback",
        "support_status": "supported" if direct else "limited_history",
        "fallback_status": "not_applicable" if direct else "regional_fallback",
        "uncertainty_status": "level_local_calibrated" if calibrated else "uncertainty_unavailable",
        "threshold_status": "unsupported" if unsupported else "supported",
        "threshold_fallback_level": "unsupported_insufficient_history" if unsupported else "hospital_pooled",
        "reason_codes": [reason] + ([] if direct else ["FORECAST_FALLBACK"]),
        "data_freshness": origin,
    }


def anomalies(*rows: tuple[str, str]) -> pd.DataFrame:
    records = []
    for hospital_id, status in rows:
        records.append(
            {
                "signal_id": f"anomaly-{hospital_id}",
                "signal_type": "observed_unusual_flow",
                "severity": "ELEVATED",
                "anomaly_status": status,
                "forecast_origin": pd.Timestamp("2025-03-17"),
                "series_id": f"hp:{hospital_id}:p1",
            }
        )
    return pd.DataFrame(
        records,
        columns=["signal_id", "signal_type", "severity", "anomaly_status", "forecast_origin", "series_id"],
    )


def test_severity_precedence_and_shorter_lead_time_ordering():
    frame = pd.DataFrame(
        [
            entity_row("watch", "WATCH", 1),
            entity_row("elevated", "ELEVATED", 1),
            entity_row("high-late", "HIGH", 5),
            entity_row("high-soon", "HIGH", 2),
        ]
    )
    ranked, unsupported, _, _ = prepare_inbox(frame, anomalies(), config())
    assert unsupported.empty
    assert ranked["hospital_id"].tolist() == ["high-soon", "high-late", "elevated", "watch"]
    assert ranked["inbox_rank"].tolist() == [1, 2, 3, 4]


def test_support_uncertainty_ratio_and_stable_entity_tie_breaking():
    frame = pd.DataFrame(
        [
            entity_row("fallback", "ELEVATED", direct=False, forecast=100.0),
            entity_row("b", "ELEVATED", calibrated=False, forecast=30.0),
            entity_row("c", "ELEVATED", forecast=13.0),
            entity_row("a", "ELEVATED", forecast=13.0),
        ]
    )
    first, _, _, _ = prepare_inbox(frame.sample(frac=1, random_state=7), anomalies(), config())
    second, _, _, _ = prepare_inbox(frame.sample(frac=1, random_state=11), anomalies(), config())
    expected = ["a", "c", "b", "fallback"]
    assert first["hospital_id"].tolist() == expected
    assert second["hospital_id"].tolist() == expected


def test_duplicate_entity_origin_is_rejected_and_persistent_warning_is_one_item():
    row = entity_row("h1", "HIGH")
    with pytest.raises(ValueError, match="duplicate entity/origin"):
        prepare_inbox(pd.DataFrame([row, row]), anomalies(), config())
    ranked, _, _, _ = prepare_inbox(pd.DataFrame([row]), anomalies(), config())
    assert len(ranked) == 1


def test_unsupported_is_separate_from_primary_ranking():
    frame = pd.DataFrame([entity_row("warn", "WATCH"), entity_row("missing", "UNSUPPORTED")])
    ranked, unsupported, low_volume, _ = prepare_inbox(frame, anomalies(), config())
    views = inbox_views(ranked, unsupported, low_volume, observed_anomaly_view(anomalies(), frame))
    assert ranked["hospital_id"].tolist() == ["warn"]
    assert unsupported["hospital_id"].tolist() == ["missing"]
    assert pd.isna(unsupported.iloc[0]["inbox_rank"])
    assert len(views["unsupported_data_quality"]) == 1


def test_zero_baseline_fractional_high_is_preserved_but_moved_to_attention():
    row = entity_row("tiny", "HIGH", threshold=0.0, forecast=0.01)
    row["uncertainty_lower"] = 0.005
    row["uncertainty_upper"] = 0.02
    source = pd.DataFrame([row])
    source_before = source.copy(deep=True)

    ranked, unsupported, low_volume, _ = prepare_inbox(source, anomalies(), config())
    assert ranked.empty
    assert unsupported.empty
    assert len(low_volume) == 1
    attention = low_volume.iloc[0]
    assert attention["source_severity"] == "HIGH"
    assert attention["severity"] == "HIGH"
    assert attention["threshold_value"] == 0.0
    assert attention["forecast_value"] == pytest.approx(0.01)
    assert attention["materiality_status"] == "zero_baseline_low_volume"
    assert attention["operational_priority_status"] == "zero_baseline_low_volume"
    assert attention["materiality_floor_expected_count"] == 1.0
    assert "low-volume zero-baseline" in attention["headline"].lower()
    assert attention["reason_codes"] == row["reason_codes"]
    pd.testing.assert_frame_equal(source, source_before)

    views = inbox_views(ranked, unsupported, low_volume, observed_anomaly_view(anomalies(), source))
    assert len(views["zero_baseline_low_volume_attention"]) == 1
    diagnostics = materiality_diagnostics(ranked, low_volume, config())
    assert diagnostics["removed_from_primary_inbox"] == 1
    assert diagnostics["source_high_before_materiality"] == 1
    assert diagnostics["source_high_after_materiality"] == 0


def test_zero_baseline_at_floor_and_positive_threshold_are_unaffected():
    at_floor = entity_row("floor", "HIGH", threshold=0.0, forecast=1.0)
    at_floor["uncertainty_lower"] = 0.5
    at_floor["uncertainty_upper"] = 2.0
    positive = entity_row("positive", "HIGH", threshold=0.5, forecast=0.6)
    positive["uncertainty_lower"] = 0.55
    positive["uncertainty_upper"] = 0.8
    ranked, unsupported, low_volume, _ = prepare_inbox(pd.DataFrame([at_floor, positive]), anomalies(), config())
    assert unsupported.empty
    assert low_volume.empty
    assert set(ranked["hospital_id"]) == {"floor", "positive"}
    assert set(ranked["materiality_status"]) == {"materiality_rule_not_triggered"}
    assert set(ranked["operational_priority_status"]) == {"primary_inbox_eligible"}


def test_fallback_explanation_is_explicit_and_non_causal():
    ranked, _, _, _ = prepare_inbox(
        pd.DataFrame([entity_row("fallback", "ELEVATED", direct=False)]), anomalies(), config()
    )
    row = ranked.iloc[0]
    assert "regional fallback because local history is limited" in " ".join(row["evidence_facts"]).lower()
    explanation = f"{row['headline']} {row['concise_reason']} {' '.join(row['evidence_facts'])}".lower()
    assert not any(term in explanation for term in ("caused", "causes", "driver", "drives", "attributable"))


def test_observed_anomaly_is_context_only_and_does_not_change_pressure_severity():
    entity = pd.DataFrame([entity_row("h1", "WATCH")])
    ranked, _, _, _ = prepare_inbox(entity, anomalies(("h1", "UNUSUAL_HIGH")), config())
    assert ranked.iloc[0]["severity"] == "WATCH"
    assert bool(ranked.iloc[0]["observed_anomaly_present"])
    observed = observed_anomaly_view(anomalies(("h1", "UNUSUAL_HIGH")), entity)
    assert observed.iloc[0]["signal_type"] == "observed_unusual_flow"
    assert observed.iloc[0]["future_pressure_severity"] == "WATCH"


def test_evidence_horizon_and_numeric_fields_reproduce_displayed_severity():
    frame = pd.DataFrame([entity_row("h1", "HIGH", 6)])
    assert_displayed_evidence_consistency(frame)
    broken = frame.copy()
    broken.loc[0, "uncertainty_lower"] = 0.0
    with pytest.raises(ValueError, match="does not reproduce"):
        assert_displayed_evidence_consistency(broken)
    wrong_day = frame.copy()
    wrong_day.loc[0, "severity_evidence_date"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="date does not match"):
        assert_displayed_evidence_consistency(wrong_day)


def test_regional_rollup_is_counts_not_a_new_risk_model():
    frame = pd.DataFrame(
        [
            entity_row("h1", "HIGH"),
            entity_row("h2", "ELEVATED", direct=False),
            entity_row("h3", "WATCH", profile_id="p2"),
            entity_row("h4", "UNSUPPORTED"),
        ]
    )
    row = regional_rollup(frame, config()).iloc[0]
    assert (row["high_entities"], row["elevated_entities"], row["watch_entities"]) == (1, 1, 1)
    assert row["unsupported_entities"] == 1
    assert row["direct_supported_share"] == pytest.approx(2 / 3)
    assert row["fallback_or_limited_share"] == pytest.approx(1 / 3)


def test_source_contract_requires_corrected_entity_unit_and_lineage_identity():
    configured = config()
    manifest = {"run_id": "pressure-v2", "scientific_identity_sha256": "pressure-science"}
    summary = {
        "run_id": "pressure-v2",
        "scientific_identity_sha256": "pressure-science",
        "signal_contract": {"version": "preventive-flow-pressure-v1"},
        "alert_units": {"entity_origin": ENTITY_ORIGIN_ALERT_UNIT},
        "protocol": {"final_test_used_for_rule_selection": False},
        "governance": {"human_review_required": True, "autonomous_action": False},
        "automatic_promotion": False,
    }
    entity = pd.DataFrame([entity_row("h1", "HIGH")])
    _require_source_contract(manifest, summary, entity, configured)
    incompatible = summary | {"scientific_identity_sha256": "different"}
    with pytest.raises(ValueError, match="scientific identity"):
        _require_source_contract(manifest, incompatible, entity, configured)
    daily_unit = summary | {"alert_units": {"entity_origin": "hospital_profile_target_origin_target_day"}}
    with pytest.raises(ValueError, match="entity/origin"):
        _require_source_contract(manifest, daily_unit, entity, configured)


def test_config_rejects_weighted_or_autonomous_priority():
    with pytest.raises(ValidationError, match="ranking order"):
        config(ranking_order=["weighted_score_desc"])
    with pytest.raises(ValidationError, match="human-review-only"):
        config(autonomous_action=True)
    with pytest.raises(ValidationError, match="exactly 1.0"):
        config(materiality_floor_expected_count=0.5)
