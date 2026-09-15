"""Overview, region and hospital × profile status (reads the marts only, except the card's series)."""

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.models import MartAreaStatus, MartHospitalProfileStatus, MartRegionProfileStatus
from app.schemas.common import Page
from app.schemas.status import (
    DailyPoint,
    ExplanationFactor,
    ExplanationSummary,
    Forecast,
    ForecastPoint,
    HospitalProfileCard,
    HospitalProfileStatus,
    OverviewResponse,
    RegionDetailResponse,
    Thresholds,
)
from app.services.common import (
    BuildInfo,
    area_kpis,
    build_info,
    hospital_row,
    hospital_status,
    load_index_order,
    region_status,
    require_profile,
    require_region,
    rnd,
)
from app.services.display import ValueFormatter

FORECAST_NOTE = (
    "Прогноз числа направлений и госпитализаций на 14 дней (модель C). Производный прогноз очереди не "
    "показывается: он не учитывает отказы и в бэктесте хуже, чем последнее известное значение очереди."
)


def overview(session: Session) -> OverviewResponse:
    info = build_info(session)
    cfg = info.config
    rows = session.scalars(select(MartAreaStatus).order_by(MartAreaStatus.area_code)).all()
    national = next(r for r in rows if r.area_level == "national")
    regions = sorted((r for r in rows if r.area_level == "region"), key=lambda r: r.area_name)
    return OverviewResponse(
        as_of_date=info.as_of_date,
        built_at=info.built_at,
        thresholds=Thresholds(
            load_index_high=cfg["status_thresholds"]["high"],
            load_index_elevated=cfg["status_thresholds"]["elevated"],
            min_registrations_28d=cfg["min_registrations_28d"],
            queue_trend_national_median_4w=rnd(
                cfg["derived"].get("queue_trend_national_median_4w", {}).get("hospital_profile"), 2
            ),
        ),
        national=area_kpis(national),
        regions=[area_kpis(r) for r in regions],
    )


def region_detail(session: Session, region_code: str) -> RegionDetailResponse:
    build_info(session)
    require_region(session, region_code)
    area = session.get(MartAreaStatus, region_code)
    m = MartRegionProfileStatus
    profiles = session.scalars(
        select(m)
        .where(m.region_code == region_code)
        .order_by(m.load_index.desc().nulls_last(), m.queue_now.desc(), m.profile_code)
    ).all()
    return RegionDetailResponse(region=area_kpis(area), profiles=[region_status(p) for p in profiles])


def region_hospitals(
    session: Session, region_code: str, profile_code: str | None, limit: int, offset: int
) -> Page[HospitalProfileStatus]:
    build_info(session)
    require_region(session, region_code)
    m = MartHospitalProfileStatus
    where = [m.region_code == region_code]
    if profile_code is not None:
        require_profile(session, profile_code)
        where.append(m.profile_code == profile_code)
    total = session.scalar(select(func.count()).select_from(m).where(*where))
    rows = session.scalars(select(m).where(*where).order_by(*load_index_order()).limit(limit).offset(offset)).all()
    return Page[HospitalProfileStatus](
        items=[hospital_status(r) for r in rows], total=total, limit=limit, offset=offset
    )


_SERIES_SQL = text("""
    SELECT date, registrations, hospitalizations, refusals, queue_length
    FROM agg_daily_hospital_profile
    WHERE org_code = :org AND profile_code = :profile AND date BETWEEN :start AND :end
    ORDER BY date
""")

_FORECAST_SQL = text("""
    SELECT target_date, horizon, pred_registrations, pred_hospitalizations, method, model_version, origin_date
    FROM pred_daily_forecast
    WHERE org_code = :org AND profile_code = :profile AND level = 'hospital'
      AND origin_date = :origin AND horizon BETWEEN 1 AND :horizon
    ORDER BY horizon
""")

# Top-5 factors per referral are stored in pred_referral.explanation. Aggregated per feature over all
# test referrals of the hospital × profile; a referral where the feature is not in its top 5 adds 0.
_FACTORS_SQL = text("""
    WITH refs AS (
        SELECT explanation FROM pred_referral
        WHERE org_code = :org AND profile_code = :profile AND registration_date BETWEEN :test_start AND :test_end
    ),
    n AS (SELECT count(*) AS n FROM refs),
    factors AS (
        SELECT m.model, e->>'feature' AS feature, split_part(e->>'text', ':', 1) AS label,
               (e->>'effect')::float8 AS effect, e->>'value' AS value
        FROM refs
        CROSS JOIN LATERAL (VALUES ('wait_time'), ('refusal_risk')) AS m(model)
        CROSS JOIN LATERAL jsonb_array_elements(refs.explanation -> m.model) AS e
    )
    SELECT f.model, f.feature, min(f.label) AS label,
           sum(abs(f.effect)) / n.n AS mean_abs_effect,
           sum(f.effect) / n.n AS mean_effect,
           count(*)::float8 / n.n AS share_in_top5,
           mode() WITHIN GROUP (ORDER BY f.value) AS most_common_value,
           n.n AS n_referrals
    FROM factors f CROSS JOIN n
    GROUP BY f.model, f.feature, n.n
    ORDER BY f.model, mean_abs_effect DESC
""")


def explanation_summary(
    session: Session, info: BuildInfo, org_code: str, profile_code: str, top_k: int = 5
) -> ExplanationSummary:
    rows = session.execute(
        _FACTORS_SQL,
        {
            "org": org_code,
            "profile": profile_code,
            "test_start": info.date("test_start"),
            "test_end": info.date("test_end"),
        },
    ).all()
    formatter = ValueFormatter.for_build(info).load_names(session, ((r.feature, r.most_common_value) for r in rows))
    n_referrals = rows[0].n_referrals if rows else 0
    out: dict[str, list[ExplanationFactor]] = {"wait_time": [], "refusal_risk": []}
    for r in rows:
        if len(out[r.model]) >= top_k:
            continue
        scale, unit, digits = (1.0, "дн.", 2) if r.model == "wait_time" else (100.0, "п.п.", 2)
        out[r.model].append(
            ExplanationFactor(
                feature=r.feature,
                label=r.label,
                mean_abs_effect=round(r.mean_abs_effect * scale, digits),
                mean_effect=round(r.mean_effect * scale, digits),
                unit=unit,
                direction="up" if r.mean_effect >= 0 else "down",
                share_in_top5=round(r.share_in_top5, 4),
                most_common_value=r.most_common_value,
                most_common_value_display=formatter.format(r.feature, r.most_common_value),
            )
        )
    return ExplanationSummary(n_referrals=n_referrals, **out)


def hospital_card(session: Session, org_code: str, profile_code: str) -> HospitalProfileCard:
    info = build_info(session)
    cfg = info.config
    row = hospital_row(session, org_code, profile_code)
    params = {"org": org_code, "profile": profile_code}

    series = [
        DailyPoint(
            date=r.date,
            registrations=r.registrations,
            hospitalizations=r.hospitalizations,
            refusals=r.refusals,
            queue=r.queue_length,
        )
        for r in session.execute(
            _SERIES_SQL, {**params, "start": info.date("series_start"), "end": info.as_of_date}
        ).all()
    ]
    fc_rows = session.execute(
        _FORECAST_SQL, {**params, "origin": info.as_of_date, "horizon": cfg["forecast_horizon"]}
    ).all()
    forecast = Forecast(
        origin_date=fc_rows[0].origin_date if fc_rows else None,
        model_version=fc_rows[0].model_version if fc_rows else None,
        method=fc_rows[0].method if fc_rows else None,
        points=[
            ForecastPoint(
                date=r.target_date,
                horizon=r.horizon,
                registrations=round(r.pred_registrations, 2),
                hospitalizations=round(r.pred_hospitalizations, 2),
            )
            for r in fc_rows
        ],
        note=FORECAST_NOTE,
    )
    factors = explanation_summary(session, info, org_code, profile_code)
    return HospitalProfileCard(
        status=hospital_status(row), series=series, forecast=forecast, explanation_factors=factors
    )
