"""All /api/v1 endpoints. Contract: docs/api.md; access control: docs/security.md.

Every endpoint except GET /health declares ViewerDep, SpecialistDep or AdminDep (checked by tools/audit.py).
"""

import datetime as dt
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import PaginationDep, SessionDep
from app.core.config import get_settings
from app.core.security import AdminDep, SpecialistDep, ViewerDep
from app.schemas.activity import AlertItem, Decision, DecisionCreate, RecommendationResponse, ReferralItem
from app.schemas.admin import AccessLogItem, ApiKeyCreate, ApiKeyCreated, ApiKeyInfo
from app.schemas.catalog import ConfigResponse, DictionariesResponse, HealthResponse, MeResponse, ModelInfo
from app.schemas.common import Message, Page, Status
from app.schemas.explanations import SignalExplanationResponse
from app.schemas.model_assurance import ModelAssuranceCapabilityResponse, ModelAssuranceSnapshotResponse
from app.schemas.operational_intelligence import (
    ForecastLevel,
    ForecastTarget,
    MaterialityStatus,
    OperationalForecastResponse,
    OperationalHospitalProfileResponse,
    OperationalOverviewResponse,
    OperationalRegionResponse,
    OperationalSignalResponse,
    Severity,
    SignalType,
    SupportStatus,
)
from app.schemas.referral_estimates import (
    QueueReferralResponse,
    ReferralEstimatesPublicationResponse,
    ReferralOrder,
)
from app.schemas.review_evidence import (
    AlternativeSetResponse,
    AlternativeSetSummaryResponse,
    ReviewOverviewResponse,
    SignalDecisionAlternativesResponse,
    SignalStressTestResponse,
)
from app.schemas.specialist import (
    AssistantReply,
    AssistantRequest,
    AssistantStatus,
    SpecialistDecision,
    SpecialistDecisionCreate,
)
from app.schemas.status import HospitalProfileCard, HospitalProfileStatus, OverviewResponse, RegionDetailResponse
from app.schemas.transparency import LedgerEntry, LedgerHead, LedgerVerification
from app.schemas.verification_worklist import (
    VerificationWorklistPublicationResponse,
    WorklistAreaResponse,
    WorklistHospitalResponse,
    WorklistOrder,
)
from app.schemas.waiting_list import (
    SupportClass,
    WaitingHospitalDetailResponse,
    WaitingHospitalResponse,
    WaitingReferralResponse,
)
from app.services import (
    activity,
    admin,
    assistant,
    catalog,
    explanations,
    export,
    model_assurance,
    operational_intelligence,
    recommend,
    referral_estimates,
    review_evidence,
    specialist_decisions,
    transparency,
    verification_worklist,
    waiting_list,
)
from app.services import status as status_service

router = APIRouter()

NOT_FOUND = {404: {"model": Message, "description": "unknown code"}}
NOT_BUILT = {503: {"model": Message, "description": "serving marts are not built (run `make marts`)"}}
AUTH = {
    401: {"model": Message, "description": "missing, invalid or revoked X-API-Key"},
    403: {"model": Message, "description": "the key's role is not allowed to do this"},
}


# ------------------------------------------------------------------------------------------ service
@router.get("/health", response_model=HealthResponse, operation_id="health_get", tags=["service"])
def get_health(session: SessionDep, response: Response) -> HealthResponse:
    """Open (no API key): database reachability and mart freshness."""
    result = catalog.health(session)
    if result.database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/me", response_model=MeResponse, responses=AUTH, operation_id="caller_get", tags=["service"])
def get_me(principal: ViewerDep) -> MeResponse:
    """Label, role and permissions of the calling API key."""
    return catalog.me(principal)


@router.get(
    "/config",
    response_model=ConfigResponse,
    responses={**AUTH, **NOT_BUILT},
    operation_id="config_get",
    tags=["service"],
)
def get_config(session: SessionDep, _: ViewerDep) -> ConfigResponse:
    """load_index weights and caps, thresholds, rules, windows and the data-source description the marts use."""
    return catalog.config(session)


# ------------------------------------------------------------------------------------------ monitoring
@router.get(
    "/overview",
    response_model=OverviewResponse,
    responses={**AUTH, **NOT_BUILT},
    operation_id="overview_get",
    tags=["monitoring"],
)
def get_overview(session: SessionDep, _: ViewerDep) -> OverviewResponse:
    """National KPIs and a table of regions."""
    return status_service.overview(session)


@router.get(
    "/regions/{region_code}",
    response_model=RegionDetailResponse,
    responses={**AUTH, **NOT_FOUND, **NOT_BUILT},
    operation_id="region_get",
    tags=["monitoring"],
)
def get_region(region_code: str, session: SessionDep, _: ViewerDep) -> RegionDetailResponse:
    """Region KPIs and every profile of the region with its status."""
    return status_service.region_detail(session, region_code)


@router.get(
    "/regions/{region_code}/hospitals",
    response_model=Page[HospitalProfileStatus],
    responses={**AUTH, **NOT_FOUND, **NOT_BUILT},
    operation_id="region_hospitals_list",
    tags=["monitoring"],
)
def get_region_hospitals(
    region_code: str,
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    profile: Annotated[str | None, Query(description="profile code, e.g. 031; all profiles if omitted")] = None,
) -> Page[HospitalProfileStatus]:
    """Hospital × profile rows of the region, highest load_index first."""
    return status_service.region_hospitals(session, region_code, profile, page.limit, page.offset)


@router.get(
    "/alerts",
    response_model=Page[AlertItem],
    responses={**AUTH, **NOT_FOUND, **NOT_BUILT},
    operation_id="alerts_list",
    tags=["monitoring"],
)
def get_alerts(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    region: Annotated[str | None, Query(description="region code; all regions if omitted")] = None,
    profile: Annotated[str | None, Query(description="profile code; all profiles if omitted")] = None,
    status_filter: Annotated[Status | None, Query(alias="status", description="load status of the row")] = None,
) -> Page[AlertItem]:
    """Hospital × profile rows with load_index ≥ 70 or an excess queue trend ≥ 5 p.p. per week."""
    return activity.alerts(session, region, profile, status_filter, page.limit, page.offset)


# ------------------------------------------------------------------------------------------ hospital
@router.get(
    "/hospitals/{org_code}/profiles/{profile_code}",
    response_model=HospitalProfileCard,
    responses={**AUTH, **NOT_FOUND, **NOT_BUILT},
    operation_id="hospital_profile_get",
    tags=["hospital"],
)
def get_hospital_profile(org_code: str, profile_code: str, session: SessionDep, _: ViewerDep) -> HospitalProfileCard:
    """Status card, daily series, 14-day forecast and aggregated explanation factors."""
    return status_service.hospital_card(session, org_code, profile_code)


@router.get(
    "/hospitals/{org_code}/profiles/{profile_code}/referrals",
    response_model=Page[ReferralItem],
    responses={**AUTH, **NOT_FOUND, **NOT_BUILT},
    operation_id="hospital_referrals_list",
    tags=["hospital"],
)
def get_hospital_referrals(
    org_code: str,
    profile_code: str,
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    sort: Annotated[
        Literal["risk", "wait"], Query(description="risk: refusal probability; wait: predicted wait")
    ] = "risk",
) -> Page[ReferralItem]:
    """Test-period referrals with model predictions and explanations."""
    return activity.referrals(session, org_code, profile_code, sort, page.limit, page.offset)


@router.get(
    "/hospitals/{org_code}/profiles/{profile_code}/recommendations",
    response_model=RecommendationResponse,
    responses={**AUTH, **NOT_FOUND, **NOT_BUILT},
    operation_id="hospital_recommendations_get",
    tags=["hospital"],
    deprecated=True,
    summary="Legacy: alternative hospitals by historical medians (not part of the control centre)",
)
def get_recommendations(org_code: str, profile_code: str, session: SessionDep, _: ViewerDep) -> RecommendationResponse:
    """Legacy rule-based comparison (v1, kept for the legacy card and its export): up to 3 other hospitals of the same
    region and profile whose patients waited less over the last 28 days, by historical medians. An association, not
    an estimate of what redirecting a patient would change; the control centre does not use it. A person decides."""
    return recommend.recommend(session, org_code, profile_code)


@router.get(
    "/hospitals/{org_code}/profiles/{profile_code}/export",
    response_class=Response,
    responses={
        **AUTH,
        **NOT_FOUND,
        **NOT_BUILT,
        200: {
            "content": {export.XLSX_MEDIA_TYPE: {}, export.PDF_MEDIA_TYPE: {}},
            "description": "the card as a file (Content-Disposition: attachment)",
        },
    },
    operation_id="hospital_export_get",
    tags=["hospital"],
)
def get_hospital_export(
    org_code: str,
    profile_code: str,
    session: SessionDep,
    _: ViewerDep,
    format: Annotated[Literal["xlsx", "pdf"], Query(description="file format")] = "xlsx",  # noqa: A002
) -> Response:
    """The hospital × profile card (status, KPIs, series, forecast, factors, historical-median alternatives,
    decisions) as a file."""
    file = export.export_card(session, org_code, profile_code, format)
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{file.filename}\"; filename*=UTF-8''{quote(file.filename)}"
        },
    )


# ------------------------------------------------------------------------------------------ decisions
@router.post(
    "/decisions",
    response_model=Decision,
    status_code=status.HTTP_201_CREATED,
    responses={
        **AUTH,
        **NOT_FOUND,
        200: {"model": Decision, "description": "idempotent replay: this idempotency_key was already stored"},
        409: {"model": Message, "description": "idempotency_key reused with a different decision"},
        422: {"description": "invalid decision"},
    },
    operation_id="decision_create",
    tags=["decisions"],
)
def post_decision(
    payload: DecisionCreate, session: SessionDep, principal: SpecialistDep, response: Response
) -> Decision:
    """Record a person's decision (confirm / reject / defer) on a hospital × profile or a recommendation."""
    decision, created = activity.create_decision(session, payload, api_key_label=principal.label)
    if not created:
        response.status_code = status.HTTP_200_OK
    return decision


@router.get(
    "/decisions",
    response_model=Page[Decision],
    responses=AUTH,
    operation_id="decisions_list",
    tags=["decisions"],
)
def get_decisions(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    org: Annotated[str | None, Query(description="hospital code")] = None,
    profile: Annotated[str | None, Query(description="profile code")] = None,
) -> Page[Decision]:
    """Decisions, newest first."""
    return activity.list_decisions(session, org, profile, page.limit, page.offset)


# ------------------------------------------------------------------------------------------ control centre
@router.post(
    "/specialist-decisions",
    response_model=SpecialistDecision,
    status_code=status.HTTP_201_CREATED,
    responses={
        **AUTH,
        200: {"model": SpecialistDecision, "description": "idempotent replay of an already stored decision"},
        409: {"model": Message, "description": "idempotency_key reused with a different decision"},
        422: {"description": "action does not fit the subject kind"},
    },
    operation_id="specialist_decision_create",
    tags=["control-centre"],
)
def post_specialist_decision(
    payload: SpecialistDecisionCreate, session: SessionDep, principal: SpecialistDep, response: Response
) -> SpecialistDecision:
    """Record the specialist's answer to a published alert (accept / decline / clarify) or to a synthetic
    admission request (confirm / decline / postpone) of the control centre."""
    decision, created = specialist_decisions.create_decision(session, payload, api_key_label=principal.label)
    if not created:
        response.status_code = status.HTTP_200_OK
    return decision


@router.get(
    "/specialist-decisions",
    response_model=Page[SpecialistDecision],
    responses=AUTH,
    operation_id="specialist_decisions_list",
    tags=["control-centre"],
)
def get_specialist_decisions(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    origin: Annotated[dt.date | None, Query(description="publication origin the demo runs on")] = None,
    run_id: Annotated[str | None, Query(description="simulation run; a restart starts a new run")] = None,
    subject_kind: Annotated[Literal["alert", "patient"] | None, Query(description="alert | patient")] = None,
) -> Page[SpecialistDecision]:
    """Specialist decisions, newest first; the control centre replays those of its current run on load."""
    return specialist_decisions.list_decisions(session, origin, run_id, subject_kind, page.limit, page.offset)


@router.get(
    "/assistant/status",
    response_model=AssistantStatus,
    responses=AUTH,
    operation_id="assistant_status",
    tags=["control-centre"],
)
def get_assistant_status(_: ViewerDep) -> AssistantStatus:
    """Whether an external model is configured on the server (the key itself is never exposed)."""
    return assistant.status(get_settings())


@router.post(
    "/assistant",
    response_model=AssistantReply,
    responses={
        **AUTH,
        502: {"model": Message, "description": "the provider answered with an error"},
        503: {"model": Message, "description": "no provider configured (ASSISTANT_API_KEY is empty)"},
    },
    operation_id="assistant_ask",
    tags=["control-centre"],
)
def post_assistant(payload: AssistantRequest, _: SpecialistDep) -> AssistantReply:
    """Ask the configured model about one subject. The browser sends the published facts and the deterministic
    explanation; the system prompt keeps the claim boundaries. Generated text, never evidence."""
    return assistant.ask(get_settings(), payload)


# ------------------------------------------------------------------------------------------ catalog
@router.get("/models", response_model=list[ModelInfo], responses=AUTH, operation_id="models_list", tags=["catalog"])
def get_models(session: SessionDep, _: ViewerDep) -> list[ModelInfo]:
    """Current model versions with model cards, headline metrics and baselines."""
    return catalog.models(session)


@router.get(
    "/model-assurance",
    response_model=ModelAssuranceSnapshotResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="model_assurance_current_get",
    tags=["assurance"],
)
def get_model_assurance(session: SessionDep, _: ViewerDep) -> ModelAssuranceSnapshotResponse:
    """Current published Model Assurance snapshot and its frozen provenance."""
    return model_assurance.current(session)


@router.get(
    "/model-assurance/capabilities",
    response_model=list[ModelAssuranceCapabilityResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="model_assurance_capabilities_list",
    tags=["assurance"],
)
def get_model_assurance_capabilities(session: SessionDep, _: ViewerDep) -> list[ModelAssuranceCapabilityResponse]:
    """Candidate-independent assurance records of the current snapshot."""
    return model_assurance.list_current_capabilities(session)


@router.get(
    "/model-assurance/capabilities/{capability_id}",
    response_model=ModelAssuranceCapabilityResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="model_assurance_capability_get",
    tags=["assurance"],
)
def get_model_assurance_capability(
    capability_id: str, session: SessionDep, _: ViewerDep
) -> ModelAssuranceCapabilityResponse:
    """One current capability assurance record by stable capability ID."""
    return model_assurance.get_current_capability(session, capability_id)


# -------------------------------------------------------------------------- operational intelligence
@router.get(
    "/operational-intelligence/overview",
    response_model=OperationalOverviewResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_intelligence_overview_get",
    tags=["operational-intelligence"],
)
def get_operational_intelligence_overview(session: SessionDep, _: ViewerDep) -> OperationalOverviewResponse:
    """Current publication metadata and national/regional operational-signal counts."""
    return operational_intelligence.overview(session)


@router.get(
    "/operational-intelligence/signals",
    response_model=Page[OperationalSignalResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_signals_list",
    tags=["operational-intelligence"],
)
def get_operational_signals(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    region: Annotated[str | None, Query(description="region code; all regions if omitted")] = None,
    org: Annotated[str | None, Query(description="hospital code; all hospitals if omitted")] = None,
    profile: Annotated[str | None, Query(description="profile code; all profiles if omitted")] = None,
    target: ForecastTarget | None = None,
    severity: Severity | None = None,
    signal_type: SignalType | None = None,
    support: SupportStatus | None = None,
    materiality: Annotated[
        MaterialityStatus | None,
        Query(
            description="materiality_status of the stored signal: materiality_rule_not_triggered = the primary inbox; "
            "zero_baseline_low_volume = below the 1.0 expected count/day floor; all signals if omitted"
        ),
    ] = None,
) -> Page[OperationalSignalResponse]:
    """Deterministically ranked attention signals with support, evidence, and provenance."""
    return operational_intelligence.list_signals(
        session,
        region_code=region,
        org_code=org,
        profile_code=profile,
        target=target,
        severity=severity,
        signal_type=signal_type,
        support_status=support,
        materiality_status=materiality,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/operational-intelligence/signals/{signal_id}",
    response_model=OperationalSignalResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_signal_get",
    tags=["operational-intelligence"],
)
def get_operational_signal(signal_id: str, session: SessionDep, _: ViewerDep) -> OperationalSignalResponse:
    """One signal's structured evidence and versioned source provenance."""
    return operational_intelligence.get_signal(session, signal_id)


@router.get(
    "/operational-intelligence/signals/{signal_id}/explanation",
    response_model=SignalExplanationResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_signal_explanation_get",
    tags=["operational-intelligence"],
)
def get_operational_signal_explanation(
    signal_id: str,
    session: SessionDep,
    _: ViewerDep,
) -> SignalExplanationResponse:
    """Evidence-grounded explanation of one published operational signal."""
    return explanations.explain_signal(session, signal_id)


@router.get(
    "/operational-intelligence/regions/{region_code}",
    response_model=OperationalRegionResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_intelligence_region_get",
    tags=["operational-intelligence"],
)
def get_operational_intelligence_region(
    region_code: str, session: SessionDep, _: ViewerDep
) -> OperationalRegionResponse:
    """Regional operational-signal summary and top deterministic inbox entries."""
    return operational_intelligence.region(session, region_code)


@router.get(
    "/operational-intelligence/hospitals/{org_code}/profiles/{profile_code}",
    response_model=OperationalHospitalProfileResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_intelligence_hospital_profile_get",
    tags=["operational-intelligence"],
)
def get_operational_intelligence_hospital_profile(
    org_code: str,
    profile_code: str,
    session: SessionDep,
    _: ViewerDep,
) -> OperationalHospitalProfileResponse:
    """Hospital/profile signals and available forecast-series facets."""
    return operational_intelligence.hospital_profile(session, org_code, profile_code)


@router.get(
    "/operational-intelligence/forecasts",
    response_model=Page[OperationalForecastResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="operational_forecasts_list",
    tags=["operational-intelligence"],
)
def get_operational_forecasts(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    origin: dt.date | None = None,
    target_date_from: dt.date | None = None,
    target_date_to: dt.date | None = None,
    level: ForecastLevel | None = None,
    region: Annotated[str | None, Query(description="region code; all regions if omitted")] = None,
    org: Annotated[str | None, Query(description="hospital code; all hospitals if omitted")] = None,
    profile: Annotated[str | None, Query(description="profile code; all profiles if omitted")] = None,
    target: ForecastTarget | None = None,
) -> Page[OperationalForecastResponse]:
    """Central forecasts with raw quantiles and calibrated uncertainty kept separate."""
    return operational_intelligence.list_forecasts(
        session,
        origin=origin,
        target_date_from=target_date_from,
        target_date_to=target_date_to,
        level=level,
        region_code=region,
        org_code=org,
        profile_code=profile,
        target=target,
        limit=page.limit,
        offset=page.offset,
    )


# ------------------------------------------------------------------------------- review evidence
@router.get(
    "/review-evidence/overview",
    response_model=ReviewOverviewResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="review_evidence_overview_get",
    tags=["review-evidence"],
)
def get_review_evidence_overview(session: SessionDep, _: ViewerDep) -> ReviewOverviewResponse:
    """Current review-evidence publication: stress-test scenario catalog and decision-alternative population."""
    return review_evidence.overview(session)


@router.get(
    "/review-evidence/signals/{signal_id}/stress-test",
    response_model=SignalStressTestResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="review_signal_stress_test_get",
    tags=["review-evidence"],
)
def get_review_signal_stress_test(signal_id: str, session: SessionDep, _: ViewerDep) -> SignalStressTestResponse:
    """Accepted non-causal stress-test outcomes and daily cells for one published signal's series."""
    return review_evidence.signal_stress_test(session, signal_id)


@router.get(
    "/review-evidence/signals/{signal_id}/decision-alternatives",
    response_model=SignalDecisionAlternativesResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="review_signal_decision_alternatives_get",
    tags=["review-evidence"],
)
def get_review_signal_decision_alternatives(
    signal_id: str, session: SessionDep, _: ViewerDep
) -> SignalDecisionAlternativesResponse:
    """Retrospective mathematical alternative sets (or abstention) evaluated for one donor signal."""
    return review_evidence.signal_decision_alternatives(session, signal_id)


@router.get(
    "/review-evidence/decision-alternatives",
    response_model=Page[AlternativeSetSummaryResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="review_decision_alternatives_list",
    tags=["review-evidence"],
)
def get_review_decision_alternatives(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    origin: dt.date | None = None,
    region: Annotated[str | None, Query(description="region code; all regions if omitted")] = None,
    org: Annotated[str | None, Query(description="donor hospital code; all hospitals if omitted")] = None,
    profile: Annotated[str | None, Query(description="profile code; all profiles if omitted")] = None,
    with_alternatives: Annotated[
        bool | None, Query(description="true: sets with published alternatives; false: abstained sets")
    ] = None,
) -> Page[AlternativeSetSummaryResponse]:
    """Donor/budget alternative-set summaries for human review; never a ranking of actions."""
    return review_evidence.list_alternative_sets(
        session,
        origin=origin,
        region_code=region,
        org_code=org,
        profile_code=profile,
        with_alternatives=with_alternatives,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/review-evidence/decision-alternatives/{set_id}",
    response_model=AlternativeSetResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="review_decision_alternative_set_get",
    tags=["review-evidence"],
)
def get_review_decision_alternative_set(set_id: str, session: SessionDep, _: ViewerDep) -> AlternativeSetResponse:
    """One alternative set with its verified alternatives, states, non-claims and provenance."""
    return review_evidence.get_alternative_set(session, set_id)


# ------------------------------------------------------------------------------- waiting list
@router.get(
    "/waiting-list/hospitals",
    response_model=Page[WaitingHospitalResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="waiting_list_hospitals_list",
    tags=["waiting-list"],
)
def get_waiting_list_hospitals(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    region: Annotated[str | None, Query(description="region code of the hospital; all regions if omitted")] = None,
    support: SupportClass | None = None,
    min_waiting: Annotated[
        int | None, Query(ge=1, description="keep hospitals with at least this many waiting")
    ] = None,
) -> Page[WaitingHospitalResponse]:
    """Hospitals with a measured queue at the published origin, largest first, each with its support class.

    Counts only: this publication carries no model output. `support_class` says whether the queue is large enough
    to read a per-hospital view from (thresholds in the publication), it is not a severity.
    """
    return waiting_list.list_hospitals(
        session,
        region_code=region,
        support_class=support,
        min_waiting=min_waiting,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/waiting-list/hospitals/{org_code}",
    response_model=WaitingHospitalDetailResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="waiting_list_hospital_get",
    tags=["waiting-list"],
)
def get_waiting_list_hospital(org_code: str, session: SessionDep, _: ViewerDep) -> WaitingHospitalDetailResponse:
    """One hospital's measured queue at the origin: totals, profile breakdown and days-already-waited histogram.

    Counts only — no model output. `observed_after_origin` totals are hindsight (what the data recorded after the
    origin) and are shown for checking an origin-time claim afterwards, never used to rank or filter.
    """
    return waiting_list.hospital_detail(session, org_code)


@router.get(
    "/waiting-list/hospitals/{org_code}/referrals",
    response_model=Page[WaitingReferralResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="waiting_list_referrals_list",
    tags=["waiting-list"],
)
def get_waiting_list_referrals(
    session: SessionDep,
    org_code: str,
    page: PaginationDep,
    _: ViewerDep,
    profile: Annotated[str | None, Query(description="profile code; all profiles if omitted")] = None,
    order: Annotated[
        Literal["longest_wait", "shortest_wait"], Query(description="by days waited at the origin")
    ] = "longest_wait",
) -> Page[WaitingReferralResponse]:
    """One hospital's real waiting list at the published origin, by days already waited.

    De-identified referrals as recorded by the Ministry of Health, with no score attached. `observed_after_origin`
    is hindsight — the outcome the data recorded after the origin — and must never be fed back into a prediction,
    a ranking or a threshold; it is there to check an origin-time claim afterwards.
    """
    return waiting_list.list_referrals(
        session,
        org_code,
        profile_code=profile,
        order=order,
        limit=page.limit,
        offset=page.offset,
    )


# ------------------------------------------------------------------- per-referral estimates
@router.get(
    "/referral-estimates/publication",
    response_model=ReferralEstimatesPublicationResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="referral_estimates_publication_get",
    tags=["referral-estimates"],
)
def get_referral_estimates_publication(session: SessionDep, _: ViewerDep) -> ReferralEstimatesPublicationResponse:
    """The active per-referral estimate publication: which model serves, why, and how well it turned out.

    `selection` is the tournament as it was decided — the metric and the rule were fixed before the run, and the
    baseline serves whenever no candidate clears them. `calibration` is hindsight over the whole published cohort
    and carries the disclosure marker; it scores the estimates afterwards and feeds nothing.
    """
    return referral_estimates.publication_response(session)


@router.get(
    "/referral-estimates/hospitals/{org_code}/referrals",
    response_model=Page[QueueReferralResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="referral_estimates_referrals_list",
    tags=["referral-estimates"],
)
def get_referral_estimates_referrals(
    session: SessionDep,
    org_code: str,
    page: PaginationDep,
    _: ViewerDep,
    profile: Annotated[str | None, Query(description="profile code; all profiles if omitted")] = None,
    order: Annotated[
        ReferralOrder, Query(description="by days waited at the origin, or by the estimated refusal risk")
    ] = "longest_wait",
    attention: Annotated[
        bool, Query(description="keep only referrals over the published refusal-attention threshold")
    ] = False,
) -> Page[QueueReferralResponse]:
    """One hospital's measured queue with each referral's origin-time estimate beside it.

    Two publications on one row: the queue is measured data with its hindsight outcome, `estimate` is model output
    produced from history up to the origin. `estimate` is null when no estimate publication stands at the queue's
    origin or when this referral is not covered; `order=highest_refusal_risk` and `attention=true` are an
    administrative follow-up order — check the referral, reach the patient — and need such a publication.
    """
    return referral_estimates.list_queue(
        session,
        org_code,
        profile_code=profile,
        order=order,
        attention_only=attention,
        limit=page.limit,
        offset=page.offset,
    )


# ------------------------------------------------------------------- verification worklist
@router.get(
    "/verification-worklist/publication",
    response_model=VerificationWorklistPublicationResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="verification_worklist_publication_get",
    tags=["verification-worklist"],
)
def get_verification_worklist_publication(session: SessionDep, _: ViewerDep) -> VerificationWorklistPublicationResponse:
    """The active verification worklist: its order, what the marks mean, and what checking in that order would find.

    A ranked administrative verification worklist for the hospitalisation bureau — the whole formal queue, ordered
    by the origin-safe verification priority for checking records against the patient and the paperwork. It is not
    a queue and never shortens one: `counts.ranked_count` equals `counts.formal_queue_count`. It is not a decision
    or a classifier either: `decision_owner` and `not_a_decision` say so on this response and on every row.
    `legacy_rule` is the earlier binary rule, kept for comparison only. `yield_curve` is hindsight against the
    whole queue's base rate and carries the disclosure marker.
    """
    return verification_worklist.publication_response(session)


@router.get(
    "/verification-worklist/regions",
    response_model=list[WorklistAreaResponse],
    responses={**AUTH, **NOT_FOUND},
    operation_id="verification_worklist_regions_list",
    tags=["verification-worklist"],
)
def get_verification_worklist_regions(session: SessionDep, _: ViewerDep) -> list[WorklistAreaResponse]:
    """Every region's formal queue, largest first, with how much of it rests on thin comparable history."""
    return verification_worklist.list_regions(session)


@router.get(
    "/verification-worklist/hospitals/{org_code}",
    response_model=WorklistHospitalResponse,
    responses={**AUTH, **NOT_FOUND},
    operation_id="verification_worklist_hospital_get",
    tags=["verification-worklist"],
)
def get_verification_worklist_hospital(
    session: SessionDep,
    org_code: str,
    page: PaginationDep,
    _: ViewerDep,
    order: Annotated[WorklistOrder, Query(description="the published ranking, or by days already waited")] = "rank",
    history_quality_warning: Annotated[
        bool | None, Query(description="keep only rows that rest on thin comparable history, or only the rest")
    ] = None,
) -> WorklistHospitalResponse:
    """One hospital's part of the verification order, in the published rank, with its own and its region's counts.

    Each row carries its priority (`verification_priority_score`), how well supported that is (`estimate_tier`,
    `comparable_training_at_risk_rows`, `history_quality_warning` with its reason), and repeats that the specialist
    decides. No row carries an outcome. `registration_date` and `hospitalization_code` come from the measured queue
    so a bureau can find the paper record; they are null when the current waiting-list publication no longer
    carries that referral.
    """
    return verification_worklist.hospital_worklist(
        session,
        org_code,
        warning=history_quality_warning,
        order=order,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/dictionaries",
    response_model=DictionariesResponse,
    responses={**AUTH, **NOT_BUILT},
    operation_id="dictionaries_get",
    tags=["catalog"],
)
def get_dictionaries(session: SessionDep, _: ViewerDep) -> DictionariesResponse:
    """Regions and profiles for UI dropdowns."""
    return catalog.dictionaries(session)


# ------------------------------------------------------------------------------------------ transparency ledger
# Public, append-only record of publications and decisions (docs/transparency-ledger.md). Every endpoint returns
# public data only — identifiers, hashes, salted commitments — so the viewer role is enough.
@router.get(
    "/transparency/head",
    response_model=LedgerHead,
    responses={**AUTH, **NOT_FOUND},
    operation_id="transparency_head_get",
    tags=["transparency"],
)
def get_transparency_head(session: SessionDep, _: ViewerDep) -> LedgerHead:
    """The newest entry: its seq (= chain length) and hash, plus the genesis hash and protocol identifiers."""
    return transparency.head(session)


@router.get(
    "/transparency/entries",
    response_model=Page[LedgerEntry],
    responses=AUTH,
    operation_id="transparency_entries_list",
    tags=["transparency"],
)
def get_transparency_entries(
    session: SessionDep,
    page: PaginationDep,
    _: ViewerDep,
    order: Annotated[Literal["desc", "asc"], Query(description="by seq; desc = newest first")] = "desc",
    event_type: Annotated[str | None, Query(max_length=64, description="e.g. decision.recorded")] = None,
) -> Page[LedgerEntry]:
    """Ledger entries by seq, exactly as hashed."""
    return transparency.entries(
        session, limit=page.limit, offset=page.offset, descending=order == "desc", event_type=event_type
    )


@router.get(
    "/transparency/entries/{seq}",
    response_model=LedgerEntry,
    responses={**AUTH, **NOT_FOUND},
    operation_id="transparency_entry_get",
    tags=["transparency"],
)
def get_transparency_entry(
    seq: Annotated[int, Path(ge=1, description="position in the ledger")], session: SessionDep, _: ViewerDep
) -> LedgerEntry:
    """One entry by its number."""
    return transparency.entry(session, seq)


@router.get(
    "/transparency/lookup",
    response_model=list[LedgerEntry],
    responses={**AUTH, 422: {"model": Message, "description": "give exactly one of entry_hash or subject"}},
    operation_id="transparency_lookup",
    tags=["transparency"],
)
def get_transparency_lookup(
    session: SessionDep,
    _: ViewerDep,
    entry_hash: Annotated[
        str | None, Query(max_length=64, description="a receipt's hash, or a prefix of at least 8 hex characters")
    ] = None,
    subject: Annotated[
        str | None, Query(max_length=256, description="e.g. specialist_decision:1427 or publication:<kind>:<id>")
    ] = None,
) -> list[LedgerEntry]:
    """Entries by hash or by subject (at most 50, by seq)."""
    return transparency.lookup(session, entry_hash=entry_hash, subject=subject)


@router.get(
    "/transparency/verify",
    response_model=LedgerVerification,
    responses=AUTH,
    operation_id="transparency_verify",
    tags=["transparency"],
)
def get_transparency_verify(session: SessionDep, _: ViewerDep) -> LedgerVerification:
    """Server verification: the whole chain, then every decision row and publication snapshot against its entry,
    including the private commitments. Reports the first problem by seq with a machine-readable reason code."""
    return transparency.verify(session)


@router.get(
    "/transparency/export",
    response_class=StreamingResponse,
    responses={
        **AUTH,
        200: {
            "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
            "description": "one canonical JSON entry per line, in seq order; no salts, no free text",
        },
    },
    operation_id="transparency_export",
    tags=["transparency"],
)
def get_transparency_export(session: SessionDep, _: ViewerDep) -> StreamingResponse:
    """The public ledger as JSONL, for tools/ledger_verify.py and the browser verification."""
    # read completely while the request's session is open; the ledger is small (docs/transparency-ledger.md §11)
    lines = list(transparency.export_lines(session))
    return StreamingResponse(
        iter(lines),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="aqyl-kezek-transparency-ledger.jsonl"'},
    )


# ------------------------------------------------------------------------------------------ admin
@router.get(
    "/admin/keys",
    response_model=list[ApiKeyInfo],
    responses=AUTH,
    operation_id="admin_keys_list",
    tags=["admin"],
)
def get_keys(session: SessionDep, _: AdminDep) -> list[ApiKeyInfo]:
    """All API keys (prefix, role, label, created, revoked) — never the keys themselves."""
    return admin.list_keys(session)


@router.post(
    "/admin/keys",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    responses=AUTH,
    operation_id="admin_key_create",
    tags=["admin"],
)
def post_key(payload: ApiKeyCreate, session: SessionDep, _: AdminDep) -> ApiKeyCreated:
    """Create a key; the response is the only place the key is ever shown."""
    return admin.create_key(session, payload.role, payload.label)


@router.post(
    "/admin/keys/{key_id}/revoke",
    response_model=ApiKeyInfo,
    responses={**AUTH, **NOT_FOUND},
    operation_id="admin_key_revoke",
    tags=["admin"],
)
def post_revoke_key(key_id: int, session: SessionDep, _: AdminDep) -> ApiKeyInfo:
    """Revoke a key (idempotent). Revoked keys get 401 from then on."""
    return admin.revoke_key(session, key_id)


@router.get(
    "/admin/access-log",
    response_model=Page[AccessLogItem],
    responses=AUTH,
    operation_id="admin_access_log_list",
    tags=["admin"],
)
def get_access_log(
    session: SessionDep,
    page: PaginationDep,
    _: AdminDep,
    key_label: Annotated[str | None, Query(description="only requests made with this key label")] = None,
    status_code: Annotated[int | None, Query(alias="status", ge=100, le=599, description="HTTP status")] = None,
) -> Page[AccessLogItem]:
    """Requests under /api, newest first."""
    return admin.access_log(session, key_label, status_code, page.limit, page.offset)
