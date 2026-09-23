"""Health, current models, serving configuration, caller identity, dictionaries."""

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import ROLE_LABELS, Principal
from app.db.models import DimOrganization, DimProfile, DimRegion, MartBuildInfo, ModelRegistry
from app.schemas.catalog import (
    ConfigResponse,
    DictionariesResponse,
    DictionaryItem,
    HealthResponse,
    MeResponse,
    ModelInfo,
    OrganizationItem,
    ProfileItem,
)
from app.services.common import build_info, rnd

MODEL_ORDER = ("wait_time", "refusal_risk", "load_forecast")


def health(session: Session) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="unavailable", marts_as_of_date=None, marts_built_at=None)
    info = session.get(MartBuildInfo, 1)
    return HealthResponse(
        status="ok" if info else "degraded",
        database="ok",
        marts_as_of_date=info.as_of_date if info else None,
        marts_built_at=info.built_at if info else None,
    )


def _split_forecast(metrics: dict) -> tuple[list[dict], list[dict], bool | None]:
    headline, baselines = [], []
    for row in metrics.get("pooled", []):
        key = {"target": row["target"], "series_level": row["eval_level"], "n": row["n"]}
        headline.append({**key, "method": "LightGBM (Poisson)", "wape": row["wape_model"], "mae": row["mae_model"]})
        for method, label in (
            ("seasonal_naive", "seasonal naive (same weekday)"),
            ("mean_28d", "mean 28d"),
            ("mean_7d", "mean 7d"),
        ):
            baselines.append({**key, "method": label, "wape": row[f"wape_{method}"], "mae": row[f"mae_{method}"]})
    verdicts = metrics.get("beats_seasonal_naive") or []
    beats = all(v.get("beats_seasonal_naive") for v in verdicts) if verdicts else None
    return headline, baselines, beats


def models(session: Session) -> list[ModelInfo]:
    rows = session.scalars(select(ModelRegistry).where(ModelRegistry.is_current.is_(True))).all()
    out = []
    for r in sorted(rows, key=lambda r: MODEL_ORDER.index(r.model_name) if r.model_name in MODEL_ORDER else 99):
        metrics = r.metrics or {}
        if r.model_name == "load_forecast":
            headline, baselines, beats = _split_forecast(metrics)
            population = metrics.get("series")
        else:
            overall = metrics.get("overall", [])
            headline = [m for m in overall if m.get("model") == "LightGBM"]
            baselines = [m for m in overall if m.get("model") != "LightGBM"]
            beats, population = None, metrics.get("population")
        card = r.card or {}
        display_names = {
            **card.get("metric_names", {}),
            **card.get("baseline_names", {}),
            **card.get("series_level_names", {}),
            **card.get("target_names", {}),
        }
        out.append(
            ModelInfo(
                model_name=r.model_name,
                title=card.get("title", r.model_name),
                intended_use=card.get("intended_use"),
                limitations=card.get("limitations", []),
                display_names=display_names,
                version=r.version,
                trained_at=r.trained_at,
                train_window=r.train_window,
                population=population,
                headline=headline,
                baselines=baselines,
                beats_baselines=beats,
            )
        )
    return out


def dictionaries(session: Session) -> DictionariesResponse:
    info = build_info(session)
    regions = session.scalars(select(DimRegion).order_by(DimRegion.region_name)).all()
    profiles = session.scalars(select(DimProfile).order_by(DimProfile.profile_code)).all()
    organizations = session.scalars(select(DimOrganization).order_by(DimOrganization.org_code)).all()
    return DictionariesResponse(
        national_code=info.national_code,
        regions=[DictionaryItem(code=r.region_code, name=r.region_name) for r in regions],
        profiles=[
            ProfileItem(code=p.profile_code, name=p.profile_name or p.profile_code, is_day_hospital=p.is_day_hospital)
            for p in profiles
        ],
        organizations=[
            OrganizationItem(code=o.org_code, name=o.org_name or o.org_code, region_code=o.region_code)
            for o in organizations
        ],
    )


def config(session: Session) -> ConfigResponse:
    info = build_info(session)
    cfg = info.config
    return ConfigResponse(
        as_of_date=info.as_of_date,
        built_at=info.built_at,
        window_days=cfg["window_days"],
        window_start=info.date("window_start"),
        trend_start=info.date("trend_start"),
        trend_end=info.date("trend_end"),
        test_start=info.date("test_start"),
        test_end=info.date("test_end"),
        series_start=info.date("series_start"),
        forecast_horizon=cfg["forecast_horizon"],
        min_registrations_28d=cfg["min_registrations_28d"],
        backlog_min_daily_throughput=cfg["backlog_min_daily_throughput"],
        high_risk_threshold=cfg["high_risk_threshold"],
        queue_trend_national_median_4w=rnd(
            cfg["derived"].get("queue_trend_national_median_4w", {}).get("hospital_profile"), 2
        ),
        load_index=cfg["load_index"],
        status_thresholds=cfg["status_thresholds"],
        alerts=cfg["alerts"],
        recommendations=cfg["recommendations"],
        data_source=cfg["data_source"],
    )


PERMISSIONS = {
    "viewer": ["read"],
    "specialist": ["read", "decide"],
    "admin": ["read", "decide", "manage_keys", "read_access_log"],
}


def me(principal: Principal) -> MeResponse:
    return MeResponse(
        label=principal.label,
        role=principal.role,
        role_label=ROLE_LABELS[principal.role],
        permissions=PERMISSIONS[principal.role],
    )
