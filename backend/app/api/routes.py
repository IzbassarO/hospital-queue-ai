"""All /api/v1 endpoints. Read-only except POST /decisions. Contract: docs/api.md."""
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response, status

from app.api.deps import PaginationDep, SessionDep
from app.schemas.activity import AlertItem, Decision, DecisionCreate, RecommendationResponse, ReferralItem
from app.schemas.catalog import DictionariesResponse, HealthResponse, ModelInfo
from app.schemas.common import Message, Page
from app.schemas.status import HospitalProfileCard, HospitalProfileStatus, OverviewResponse, RegionDetailResponse
from app.services import activity, catalog, recommend, status as status_service

router = APIRouter()

NOT_FOUND = {404: {"model": Message, "description": "unknown code"}}
NOT_BUILT = {503: {"model": Message, "description": "serving marts are not built (run `make marts`)"}}


@router.get("/health", response_model=HealthResponse, tags=["service"])
def get_health(session: SessionDep, response: Response) -> HealthResponse:
    result = catalog.health(session)
    if result.database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/overview", response_model=OverviewResponse, responses=NOT_BUILT, tags=["monitoring"])
def get_overview(session: SessionDep) -> OverviewResponse:
    """National KPIs and a table of regions."""
    return status_service.overview(session)


@router.get("/regions/{region_code}", response_model=RegionDetailResponse, responses={**NOT_FOUND, **NOT_BUILT},
            tags=["monitoring"])
def get_region(region_code: str, session: SessionDep) -> RegionDetailResponse:
    """Region KPIs and every profile of the region with its status."""
    return status_service.region_detail(session, region_code)


@router.get("/regions/{region_code}/hospitals", response_model=Page[HospitalProfileStatus],
            responses={**NOT_FOUND, **NOT_BUILT}, tags=["monitoring"])
def get_region_hospitals(
    region_code: str, session: SessionDep, page: PaginationDep,
    profile: Annotated[str | None, Query(description="profile code, e.g. 031; all profiles if omitted")] = None,
) -> Page[HospitalProfileStatus]:
    """Hospital × profile rows of the region, highest load_index first."""
    return status_service.region_hospitals(session, region_code, profile, page.limit, page.offset)


@router.get("/hospitals/{org_code}/profiles/{profile_code}", response_model=HospitalProfileCard,
            responses={**NOT_FOUND, **NOT_BUILT}, tags=["hospital"])
def get_hospital_profile(org_code: str, profile_code: str, session: SessionDep) -> HospitalProfileCard:
    """Status card, daily series, 14-day forecast and aggregated explanation factors."""
    return status_service.hospital_card(session, org_code, profile_code)


@router.get("/hospitals/{org_code}/profiles/{profile_code}/referrals", response_model=Page[ReferralItem],
            responses={**NOT_FOUND, **NOT_BUILT}, tags=["hospital"])
def get_hospital_referrals(
    org_code: str, profile_code: str, session: SessionDep, page: PaginationDep,
    sort: Annotated[Literal["risk", "wait"], Query(description="risk: refusal probability; wait: predicted wait")] = "risk",
) -> Page[ReferralItem]:
    """Test-period referrals with model predictions and explanations."""
    return activity.referrals(session, org_code, profile_code, sort, page.limit, page.offset)


@router.get("/hospitals/{org_code}/profiles/{profile_code}/recommendations", response_model=RecommendationResponse,
            responses={**NOT_FOUND, **NOT_BUILT}, tags=["hospital"])
def get_recommendations(org_code: str, profile_code: str, session: SessionDep) -> RecommendationResponse:
    """Rule-based v1: up to 3 alternative hospitals in the same region and profile."""
    return recommend.recommend(session, org_code, profile_code)


@router.post("/decisions", response_model=Decision, status_code=status.HTTP_201_CREATED,
             responses={**NOT_FOUND, 422: {"description": "invalid decision"}}, tags=["decisions"])
def post_decision(payload: DecisionCreate, session: SessionDep) -> Decision:
    """Record a person's decision (confirm / reject / defer) on a hospital × profile or a recommendation."""
    return activity.create_decision(session, payload)


@router.get("/decisions", response_model=Page[Decision], tags=["decisions"])
def get_decisions(
    session: SessionDep, page: PaginationDep,
    org: Annotated[str | None, Query(description="hospital code")] = None,
    profile: Annotated[str | None, Query(description="profile code")] = None,
) -> Page[Decision]:
    """Decisions, newest first."""
    return activity.list_decisions(session, org, profile, page.limit, page.offset)


@router.get("/alerts", response_model=Page[AlertItem], responses={**NOT_FOUND, **NOT_BUILT}, tags=["monitoring"])
def get_alerts(
    session: SessionDep, page: PaginationDep,
    region: Annotated[str | None, Query(description="region code; all regions if omitted")] = None,
) -> Page[AlertItem]:
    """Hospital × profile rows with load_index ≥ 70 or a queue growing ≥ 5% per week."""
    return activity.alerts(session, region, page.limit, page.offset)


@router.get("/models", response_model=list[ModelInfo], tags=["catalog"])
def get_models(session: SessionDep) -> list[ModelInfo]:
    """Current model versions with headline metrics and baselines."""
    return catalog.models(session)


@router.get("/dictionaries", response_model=DictionariesResponse, responses=NOT_BUILT, tags=["catalog"])
def get_dictionaries(session: SessionDep) -> DictionariesResponse:
    """Regions and profiles for UI dropdowns."""
    return catalog.dictionaries(session)
