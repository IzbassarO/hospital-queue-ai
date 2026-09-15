"""Health, current models, dictionaries."""
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import DimProfile, DimRegion, MartBuildInfo, ModelRegistry
from app.schemas.catalog import DictionariesResponse, DictionaryItem, HealthResponse, ModelInfo, ProfileItem
from app.services.common import build_info

MODEL_TITLES = {
    "wait_time": "A · Время ожидания госпитализации (дни)",
    "refusal_risk": "B · Риск отказа в госпитализации (вероятность)",
    "load_forecast": "C · Прогноз направлений и госпитализаций на 14 дней",
}
MODEL_ORDER = ("wait_time", "refusal_risk", "load_forecast")


def health(session: Session) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return HealthResponse(status="degraded", database="unavailable", marts_as_of_date=None, marts_built_at=None)
    info = session.get(MartBuildInfo, 1)
    return HealthResponse(status="ok" if info else "degraded", database="ok",
                          marts_as_of_date=info.as_of_date if info else None,
                          marts_built_at=info.built_at if info else None)


def _split_forecast(metrics: dict) -> tuple[list[dict], list[dict], bool | None]:
    headline, baselines = [], []
    for row in metrics.get("pooled", []):
        key = {"target": row["target"], "series_level": row["eval_level"], "n": row["n"]}
        headline.append({**key, "method": "LightGBM (Poisson)", "wape": row["wape_model"], "mae": row["mae_model"]})
        for method, label in (("seasonal_naive", "seasonal naive (same weekday)"), ("mean_28d", "mean 28d"),
                              ("mean_7d", "mean 7d")):
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
        out.append(ModelInfo(model_name=r.model_name, title=MODEL_TITLES.get(r.model_name, r.model_name),
                             version=r.version, trained_at=r.trained_at, train_window=r.train_window,
                             population=population, headline=headline, baselines=baselines, beats_baselines=beats))
    return out


def dictionaries(session: Session) -> DictionariesResponse:
    info = build_info(session)
    regions = session.scalars(select(DimRegion).order_by(DimRegion.region_name)).all()
    profiles = session.scalars(select(DimProfile).order_by(DimProfile.profile_code)).all()
    return DictionariesResponse(
        national_code=info.national_code,
        regions=[DictionaryItem(code=r.region_code, name=r.region_name) for r in regions],
        profiles=[ProfileItem(code=p.profile_code, name=p.profile_name or p.profile_code,
                              is_day_hospital=p.is_day_hospital) for p in profiles],
    )
