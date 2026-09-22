"""Evidence-grounded operational-signal explanation tests."""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator

import httpx
import pytest

from app.api import routes
from app.db.session import SessionLocal
from app.schemas.explanations import NarratedSections
from app.services import explanations, operational_intelligence
from conftest import API
from test_operational_intelligence import (
    _bundle,
    _parsed,
    _set_identity,
    preserve_current_snapshot,  # noqa: F401 - imported pytest fixture
)


@pytest.fixture
def published_snapshot() -> Iterator[operational_intelligence.PublicationResult]:
    with SessionLocal() as session:
        result = operational_intelligence.publish(session, _parsed(_bundle()))
    yield result


def _explain(signal_id: str):
    with SessionLocal() as session:
        return explanations.explain_signal(session, signal_id)


def _publish_modified(mutator) -> None:
    payload = _bundle()
    mutator(payload)
    _set_identity(payload)
    with SessionLocal() as session:
        operational_intelligence.publish(session, _parsed(payload))


def test_high_and_elevated_explanations_are_deterministic(
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    direct = _explain("signal-direct")
    fallback = _explain("signal-fallback")

    assert direct.subject.severity == "HIGH"
    assert fallback.subject.severity == "ELEVATED"
    assert explanations.configured_narrator() is None
    assert direct.generation_mode == fallback.generation_mode == "DETERMINISTIC"
    assert "historical_flow_proxy_v1" in direct.summary
    assert direct.subject.signal_id == "signal-direct"


@pytest.mark.parametrize("severity", ["WATCH", "NORMAL"])
def test_watch_and_normal_keep_attention_semantics(
    severity: str,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    def mutate(payload: dict) -> None:
        payload["signals"][0]["severity"] = severity
        payload["signals"][0]["threshold_value"] = 6.0
        payload["signals"][0]["concise_reason"] = f"Published severity is {severity}."

    _publish_modified(mutate)
    result = _explain("signal-direct")
    assert result.subject.severity == severity
    assert f"A {severity} preventive-flow signal" in result.summary
    assert "attention flag for human review" in result.summary


def test_direct_fallback_and_unsupported_support_remain_explicit(
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    assert _explain("signal-direct").support.status == "DIRECT_SUPPORTED"
    fallback = _explain("signal-fallback")
    assert fallback.support.status == "FALLBACK_LIMITED"
    assert fallback.support.fallback_status == "REGION_PROFILE_FALLBACK"

    def unsupported(payload: dict) -> None:
        payload["signals"][1]["severity"] = "UNSUPPORTED"
        payload["signals"][1]["support_status"] = "UNSUPPORTED"
        payload["signals"][1]["fallback_status"] = "UNSUPPORTED"
        payload["forecasts"][1]["support_status"] = "UNSUPPORTED"
        payload["forecasts"][1]["fallback_status"] = "UNSUPPORTED"

    _publish_modified(unsupported)
    result = _explain("signal-fallback")
    assert result.support.status == "UNSUPPORTED"
    assert "must not be treated as supported evidence" in result.support.narrative


def test_calibrated_and_missing_uncertainty_are_not_conflated(
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    calibrated = _explain("signal-direct").uncertainty
    limited = _explain("signal-fallback").uncertainty

    assert calibrated.status == "CALIBRATED"
    assert calibrated.calibrated_lower == 4.0
    assert calibrated.calibrated_upper == 9.0
    assert calibrated.raw_quantiles is not None
    assert "4 to 9" in calibrated.narrative
    assert limited.status == "INSUFFICIENT_CALIBRATION_SUPPORT"
    assert limited.calibrated_lower is None
    assert "not available" in limited.narrative


def test_pressure_limit_and_anomaly_distinction_are_always_preserved(
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    pressure = _explain("signal-direct")
    anomaly = _explain("signal-anomaly")

    assert any("historical_flow_proxy_v1" in item for item in pressure.limitations)
    assert any("not beds, occupancy, staffed capacity" in item for item in pressure.limitations)
    assert anomaly.subject.signal_type == "observed_unusual_flow"
    assert "retrospective anomaly" in anomaly.summary
    assert "distinct from preventive forecast pressure" in anomaly.summary
    assert anomaly.uncertainty.central_value is None
    assert {item.code for item in anomaly.key_evidence} >= {"observed_value", "robust_z"}


def test_review_questions_are_not_recommendations_and_provenance_is_bounded(
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    result = _explain("signal-direct")
    rendered = json.dumps(result.model_dump(mode="json"))
    prohibited = ("recommend", "route", "allocate", "intervene", "autonomous")

    assert all(question.endswith("?") for question in result.suggested_review_questions)
    assert not any(term in " ".join(result.suggested_review_questions).lower() for term in prohibited)
    assert result.provenance.publication_identity_sha256 == published_snapshot.publication_identity_sha256
    assert result.provenance.assurance_identity_sha256 == "a" * 64
    assert {fact.capability_id for fact in result.provenance.model_assurance_capabilities} >= {
        "preventive_flow_pressure",
        "signal_prioritization",
    }
    assert "artifact_path" not in rendered
    assert "run_manifest" not in rendered
    assert "/Users/" not in rendered


class _BrokenNarrator:
    def narrate(self, context, deterministic):
        raise RuntimeError("provider unavailable")


class _ForbiddenNarrator:
    def narrate(self, context, deterministic):
        return {
            "summary": (
                "historical_flow_proxy_v1 proves the capacity planner must route patients. "
                f"{context.support.status} {context.uncertainty.status}."
            ),
            "why_flagged": ["Physical capacity will be exceeded."],
        }


class _ValidNarrator:
    def narrate(self, context, deterministic):
        return NarratedSections(
            summary=(
                "Published historical_flow_proxy_v1 evidence is presented for human review; "
                f"support is {context.support.status} and uncertainty is {context.uncertainty.status}."
            ),
            why_flagged=[context.concise_reason],
        )


@pytest.mark.parametrize("narrator", [_BrokenNarrator(), _ForbiddenNarrator()])
def test_narrator_failure_or_forbidden_claim_falls_back(
    narrator,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    with SessionLocal() as session:
        result = explanations.explain_signal(session, "signal-direct", narrator=narrator)
    assert result.generation_mode == "DETERMINISTIC_FALLBACK"
    assert "capacity planner" not in result.summary


def test_valid_bounded_narrator_cannot_change_structured_facts(
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    deterministic = _explain("signal-direct")
    with SessionLocal() as session:
        narrated = explanations.explain_signal(session, "signal-direct", narrator=_ValidNarrator())
    assert narrated.generation_mode == "NARRATED"
    assert narrated.key_evidence == deterministic.key_evidence
    assert narrated.uncertainty == deterministic.uncertainty
    assert narrated.support == deterministic.support
    assert narrated.provenance == deterministic.provenance


@pytest.mark.anyio
async def test_explanation_api_auth_not_found_and_contract(
    client: httpx.AsyncClient,
    anon_client: httpx.AsyncClient,
    published_snapshot: operational_intelligence.PublicationResult,
) -> None:
    path = f"{API}/operational-intelligence/signals/signal-direct/explanation"
    assert (await anon_client.get(path)).status_code == 401
    response = await client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "subject",
        "summary",
        "why_flagged",
        "key_evidence",
        "uncertainty",
        "support",
        "limitations",
        "suggested_review_questions",
        "provenance",
        "generation_mode",
    }
    assert body["generation_mode"] == "DETERMINISTIC"
    missing = await client.get(f"{API}/operational-intelligence/signals/not-real/explanation")
    assert missing.status_code == 404


def test_backend_explanation_layer_has_no_ml_or_filesystem_dependency() -> None:
    source = "\n".join(
        (
            inspect.getsource(explanations),
            inspect.getsource(routes.get_operational_signal_explanation),
        )
    )
    assert "hqai_ml" not in source
    assert "read_text" not in source
    assert "read_bytes" not in source
    assert "artifact" not in source.lower()
    assert routes.get_operational_signal_explanation.__name__ == "get_operational_signal_explanation"
