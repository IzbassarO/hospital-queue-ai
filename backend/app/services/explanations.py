"""Evidence-grounded explanations over published PostgreSQL read models."""

from __future__ import annotations

import json
import re
from typing import Protocol

from sqlalchemy.orm import Session

from app.repositories import explanations as repository
from app.schemas.explanations import (
    ExplanationCapabilityFact,
    ExplanationEvidenceItem,
    ExplanationProvenance,
    ExplanationSubject,
    ExplanationSupport,
    ExplanationUncertainty,
    NarratedSections,
    SignalExplanationContext,
    SignalExplanationResponse,
)
from app.services.common import NotFoundError

_CAPABILITIES_BY_SIGNAL = {
    "preventive_flow_pressure": {
        "flow_hierarchical_coherence",
        "flow_temporal_calibration",
        "preventive_flow_pressure",
        "signal_prioritization",
    },
    "observed_unusual_flow": {"observed_unusual_flow", "signal_prioritization"},
}
_FORBIDDEN_CLAIM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bAI recommender\b",
        r"\bpatient router\b",
        r"\bautonomous routing(?: system)?\b",
        r"\bcapacity optimizer\b",
        r"\bcapacity planner\b",
        r"\bDigital Twin\b",
        r"\bcausal simulator\b",
        r"\bintervention engine\b",
        r"\b(?:capacity|beds?|occupancy)\b",
        r"\brout(?:e|es|ed|ing)\b",
        r"\bcaus(?:al|e|es|ed|ing)\b",
        r"\b(?:should|must|recommend(?:ed|ation)?|allocate|intervene)\b",
    )
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?%?")


class ExplanationNarrator(Protocol):
    """Optional provider: receives only bounded published context and deterministic text."""

    def narrate(
        self,
        context: SignalExplanationContext,
        deterministic: SignalExplanationResponse,
    ) -> NarratedSections | dict:
        """Rewrite the summary and reasons without adding facts or recommendations."""


def configured_narrator() -> ExplanationNarrator | None:
    """No external narrator is configured in v1; deterministic generation is always available."""
    return None


def _number(value: float | int) -> str:
    return f"{value:g}"


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _uncertainty(rows: repository.SignalExplanationRows) -> ExplanationUncertainty:
    signal = rows.signal
    forecast = rows.forecast
    central = signal.forecast_value if signal.forecast_value is not None else None
    if central is None and forecast is not None:
        central = forecast.central_value

    raw = None
    if forecast is not None and forecast.raw_p10 is not None:
        raw = {
            "p10": forecast.raw_p10,
            "p50": forecast.raw_p50,
            "p90": forecast.raw_p90,
            "semantics": "UNCHANGED_MODEL_EVIDENCE",
        }
    if signal.uncertainty_status == "CALIBRATED":
        narrative = (
            f"The calibrated uncertainty interval is {_number(signal.uncertainty_lower)} to "
            f"{_number(signal.uncertainty_upper)}."
        )
    else:
        narrative = (
            f"A calibrated uncertainty interval is not available; the published uncertainty status is "
            f"{signal.uncertainty_status}."
        )
    return ExplanationUncertainty(
        status=signal.uncertainty_status,
        narrative=narrative,
        central_value=central,
        central_semantics=forecast.central_semantics if forecast is not None else None,
        target_date=forecast.target_date if forecast is not None else signal.first_crossing_date,
        horizon_days=forecast.horizon if forecast is not None else signal.lead_time_days,
        raw_quantiles=raw,
        calibrated_lower=signal.uncertainty_lower,
        calibrated_upper=signal.uncertainty_upper,
        nominal_coverage=forecast.calibration_nominal_coverage if forecast is not None else None,
        calibration_status=forecast.calibration_status if forecast is not None else None,
    )


def _support(rows: repository.SignalExplanationRows) -> ExplanationSupport:
    signal = rows.signal
    forecast = rows.forecast
    narratives = {
        "DIRECT_SUPPORTED": "The published signal is directly supported for this series.",
        "FALLBACK_LIMITED": (
            f"The published signal is fallback-limited ({signal.fallback_status}); interpret it with that limitation."
        ),
        "UNSUPPORTED": "The published signal is unsupported and must not be treated as supported evidence.",
    }
    return ExplanationSupport(
        status=signal.support_status,
        fallback_status=signal.fallback_status,
        prediction_source=forecast.prediction_source if forecast is not None else None,
        narrative=narratives[signal.support_status],
    )


def _provenance(rows: repository.SignalExplanationRows) -> ExplanationProvenance:
    signal = rows.signal
    keys = set(signal.provenance_keys)
    if rows.forecast is not None:
        keys.update(rows.forecast.provenance_keys)
    source_provenance = {key: rows.snapshot.source_provenance[key] for key in sorted(keys)}
    relevant = _CAPABILITIES_BY_SIGNAL[signal.signal_type]
    capabilities = [
        ExplanationCapabilityFact(
            capability_id=row.capability_id,
            evidence_status=row.evidence_status,
            acceptance_verdict=row.acceptance_verdict,
            product_consumption_status=row.product_consumption_status,
            human_review_required=row.human_review_required,
            autonomous_action=row.autonomous_action,
            capacity_checked=row.capacity_checked,
            causal_effect_claimed=row.causal_effect_claimed,
        )
        for row in rows.capabilities
        if row.capability_id in relevant
    ]
    return ExplanationProvenance(
        publication_id=rows.snapshot.publication_id,
        publication_identity_sha256=rows.snapshot.publication_identity_sha256,
        assurance_identity_sha256=rows.snapshot.assurance_identity_sha256,
        source_provenance=source_provenance,
        model_assurance_capabilities=capabilities,
    )


def build_signal_context(session: Session, signal_id: str) -> SignalExplanationContext:
    rows = repository.signal_explanation(session, signal_id)
    if rows is None:
        raise NotFoundError(f"unknown current operational signal {signal_id!r}")
    signal = rows.signal
    subject = ExplanationSubject(
        signal_id=signal.signal_id,
        signal_type=signal.signal_type,
        series_id=signal.series_id,
        target=signal.target,
        origin=signal.origin,
        org_code=signal.org_code,
        region_code=signal.region_code,
        profile_code=signal.profile_code,
        severity=signal.severity,
        inbox_rank=signal.inbox_rank,
    )
    limitations = [*rows.snapshot.limitations, *signal.details.get("limitations", [])]
    for capability in rows.capabilities:
        if capability.capability_id in _CAPABILITIES_BY_SIGNAL[signal.signal_type]:
            limitations.extend(capability.details.get("limitations", []))
    if signal.signal_type == "preventive_flow_pressure":
        limitations.append(
            "historical_flow_proxy_v1 is a historical-flow count reference, not beds, occupancy, staffed "
            "capacity, confirmed physical overload, or physical feasibility."
        )
    else:
        limitations.append(
            "Observed unusual flow is retrospective anomaly evidence, not a future-pressure, capacity, or causal claim."
        )
    limitations.append("This explanation supports human review only and does not prescribe or automate action.")
    return SignalExplanationContext(
        subject=subject,
        headline=signal.headline,
        concise_reason=signal.concise_reason,
        materiality_status=signal.materiality_status,
        pressure_basis=signal.pressure_basis,
        threshold_value=signal.threshold_value,
        threshold_status=signal.threshold_status,
        forecast_value=signal.forecast_value,
        first_crossing_date=signal.first_crossing_date,
        lead_time_days=signal.lead_time_days,
        reason_codes=signal.reason_codes,
        evidence_facts=signal.evidence_facts,
        anomaly_evidence=signal.details.get("anomaly_evidence"),
        uncertainty=_uncertainty(rows),
        support=_support(rows),
        limitations=_deduplicate(limitations),
        provenance=_provenance(rows),
    )


def render_deterministic(context: SignalExplanationContext) -> SignalExplanationResponse:
    subject = context.subject
    evidence = [ExplanationEvidenceItem(code="reason_code", statement=code) for code in context.reason_codes]
    evidence.extend(
        ExplanationEvidenceItem(code="published_evidence_fact", statement=fact) for fact in context.evidence_facts
    )
    why = [context.concise_reason]

    if subject.signal_type == "preventive_flow_pressure":
        summary = (
            f"A {subject.severity} preventive-flow signal was published for {subject.target} using "
            "historical_flow_proxy_v1. It is an attention flag for human review, not a physical-capacity finding."
        )
        if context.forecast_value is not None:
            evidence.append(
                ExplanationEvidenceItem(
                    code="central_forecast",
                    statement="Published central forecast value.",
                    value=context.forecast_value,
                )
            )
        if context.threshold_value is not None:
            evidence.append(
                ExplanationEvidenceItem(
                    code="historical_flow_reference",
                    statement="Published historical-flow reference value.",
                    value=context.threshold_value,
                )
            )
        if context.first_crossing_date is not None:
            why.append(
                f"The published first crossing date is {context.first_crossing_date.isoformat()} with a "
                f"{context.lead_time_days}-day lead time."
            )
    else:
        summary = (
            f"A {subject.severity} observed-unusual-flow signal was published for {subject.target}. "
            "It describes a retrospective anomaly and is distinct from preventive forecast pressure."
        )
        anomaly = context.anomaly_evidence or {}
        for code, label in (
            ("observed_value", "Published observed value."),
            ("weekly_residual", "Published weekly residual."),
            ("robust_z", "Published robust z-score."),
            ("reference_sample_count", "Published reference sample count."),
        ):
            if anomaly.get(code) is not None:
                evidence.append(ExplanationEvidenceItem(code=code, statement=label, value=anomaly[code]))

    if context.materiality_status is not None:
        evidence.append(
            ExplanationEvidenceItem(
                code="materiality_status",
                statement="Published materiality classification.",
                value=context.materiality_status,
            )
        )
    questions = [
        "What current local operational context is relevant to a human review?",
        "How do the published uncertainty and support limitations affect interpretation of this signal?",
        "Is more recent observed information available for comparison?",
    ]
    if context.support.status == "FALLBACK_LIMITED":
        questions.append("What direct local evidence, if available, differs from the published fallback evidence?")
    if context.support.status == "UNSUPPORTED":
        questions.append("What supported evidence would be needed before drawing an operational conclusion?")
    if subject.signal_type == "observed_unusual_flow":
        questions.append("Does the observed anomaly persist in subsequent observed data?")
    return SignalExplanationResponse(
        subject=subject,
        summary=summary,
        why_flagged=why,
        key_evidence=evidence,
        uncertainty=context.uncertainty,
        support=context.support,
        limitations=context.limitations,
        suggested_review_questions=questions,
        provenance=context.provenance,
        generation_mode="DETERMINISTIC",
    )


def _validated_narration(
    value: NarratedSections | dict,
    context: SignalExplanationContext,
) -> NarratedSections:
    narration = NarratedSections.model_validate(value)
    text = "\n".join([narration.summary, *narration.why_flagged])
    if any(pattern.search(text) for pattern in _FORBIDDEN_CLAIM_PATTERNS):
        raise ValueError("narration contains a forbidden claim")
    allowed_numbers = set(_NUMBER.findall(json.dumps(context.model_dump(mode="json"), sort_keys=True)))
    if not set(_NUMBER.findall(text)).issubset(allowed_numbers):
        raise ValueError("narration introduced an unsupported numeric fact")
    if context.subject.signal_type == "preventive_flow_pressure" and "historical_flow_proxy_v1" not in text:
        raise ValueError("narration omitted the pressure-basis boundary")
    if context.support.status not in text or context.uncertainty.status not in text:
        raise ValueError("narration omitted support or uncertainty semantics")
    if context.subject.signal_type == "observed_unusual_flow" and "observed" not in text.lower():
        raise ValueError("narration omitted observed-anomaly semantics")
    return narration


def explain_signal(
    session: Session,
    signal_id: str,
    *,
    narrator: ExplanationNarrator | None = None,
) -> SignalExplanationResponse:
    context = build_signal_context(session, signal_id)
    deterministic = render_deterministic(context)
    provider = narrator if narrator is not None else configured_narrator()
    if provider is None:
        return deterministic
    try:
        narrated = _validated_narration(provider.narrate(context, deterministic), context)
    except Exception:
        return deterministic.model_copy(update={"generation_mode": "DETERMINISTIC_FALLBACK"})
    return deterministic.model_copy(
        update={
            "summary": narrated.summary,
            "why_flagged": narrated.why_flagged,
            "generation_mode": "NARRATED",
        }
    )
