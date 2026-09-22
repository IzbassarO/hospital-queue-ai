"""All /api/v1 endpoints. Contract: docs/api.md; access control: docs/security.md.

Every endpoint except GET /health declares ViewerDep, SpecialistDep or AdminDep (checked by tools/audit.py).
"""

import datetime as dt
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PaginationDep, SessionDep
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
    OperationalForecastResponse,
    OperationalHospitalProfileResponse,
    OperationalOverviewResponse,
    OperationalRegionResponse,
    OperationalSignalResponse,
    Severity,
    SignalType,
    SupportStatus,
)
from app.schemas.status import HospitalProfileCard, HospitalProfileStatus, OverviewResponse, RegionDetailResponse
from app.services import (
    activity,
    admin,
    catalog,
    explanations,
    export,
    model_assurance,
    operational_intelligence,
    recommend,
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
)
def get_recommendations(org_code: str, profile_code: str, session: SessionDep, _: ViewerDep) -> RecommendationResponse:
    """Rule-based v1: up to 3 alternative hospitals in the same region and profile."""
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
    """The hospital × profile card (status, KPIs, series, forecast, factors, recommendations, decisions) as a file."""
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
