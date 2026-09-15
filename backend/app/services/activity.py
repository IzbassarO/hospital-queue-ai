"""Referrals of a hospital × profile, decisions (human in the loop), alerts."""

from typing import Literal

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.db.models import DecisionLog, DimOrganization, MartHospitalProfileStatus
from app.schemas.activity import AlertItem, Decision, DecisionCreate, ReferralItem
from app.schemas.common import Page
from app.services.common import (
    ValidationError,
    build_info,
    hospital_row,
    load_index_order,
    require_profile,
    require_region,
    rnd,
)
from app.services.display import ValueFormatter, explanation_pairs, with_display

# ------------------------------------------------------------------------------------------ referrals
_REFERRAL_ORDER = {
    "risk": "pr.pred_refusal_prob DESC, pr.pred_wait_days DESC",
    "wait": "pr.pred_wait_days DESC, pr.pred_refusal_prob DESC",
}


def referrals(
    session: Session, org_code: str, profile_code: str, sort: Literal["risk", "wait"], limit: int, offset: int
) -> Page[ReferralItem]:
    info = build_info(session)
    hospital_row(session, org_code, profile_code)
    params = {
        "org": org_code,
        "profile": profile_code,
        "start": info.date("test_start"),
        "end": info.date("test_end"),
        "limit": limit,
        "offset": offset,
        "high_risk": info.config["high_risk_threshold"],
    }
    where = "pr.org_code = :org AND pr.profile_code = :profile AND pr.registration_date BETWEEN :start AND :end"
    total = session.execute(text(f"SELECT count(*) FROM pred_referral pr WHERE {where}"), params).scalar_one()
    rows = session.execute(
        text(f"""
        SELECT pr.hospitalization_code, pr.registration_date, fr.icd10_code, fr.referral_purpose,
               pr.pred_wait_days, pr.pred_refusal_prob, pr.explanation
        FROM pred_referral pr
        LEFT JOIN fact_referral fr ON fr.referral_id = pr.referral_id
        WHERE {where}
        ORDER BY {_REFERRAL_ORDER[sort]}, pr.hospitalization_code
        LIMIT :limit OFFSET :offset
    """),
        params,
    ).all()
    formatter = ValueFormatter.for_build(info).load_names(session, explanation_pairs(r.explanation for r in rows))
    items = [
        ReferralItem(
            hospitalization_code=r.hospitalization_code,
            registration_date=r.registration_date,
            icd10_code=r.icd10_code,
            referral_purpose=r.referral_purpose,
            pred_wait_days=round(r.pred_wait_days, 1),
            pred_refusal_prob=round(r.pred_refusal_prob, 4),
            is_high_risk=r.pred_refusal_prob >= params["high_risk"],
            explanation=with_display(r.explanation, formatter),
        )
        for r in rows
    ]
    return Page[ReferralItem](items=items, total=total, limit=limit, offset=offset)


# ------------------------------------------------------------------------------------------ decisions
def _decision(row: DecisionLog) -> Decision:
    return Decision(
        id=row.id,
        created_at=row.created_at,
        region_code=row.region_code,
        org_code=row.org_code,
        profile_code=row.profile_code,
        recommendation_id=row.recommendation_id,
        action=row.action,
        comment=row.comment,
        actor=row.actor,
    )


def create_decision(session: Session, payload: DecisionCreate) -> Decision:
    require_region(session, payload.region_code)
    require_profile(session, payload.profile_code)
    org = session.get(DimOrganization, payload.org_code)
    if org is None:
        raise ValidationError(f"unknown hospital {payload.org_code!r}")
    if org.region_code != payload.region_code:
        raise ValidationError(
            f"hospital {payload.org_code!r} belongs to region {org.region_code!r}, not {payload.region_code!r}"
        )
    if session.get(MartHospitalProfileStatus, (payload.org_code, payload.profile_code)) is None:
        raise ValidationError(f"hospital {payload.org_code!r} has no referrals for profile {payload.profile_code!r}")
    row = DecisionLog(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return _decision(row)


def list_decisions(
    session: Session, org_code: str | None, profile_code: str | None, limit: int, offset: int
) -> Page[Decision]:
    where = []
    if org_code is not None:
        where.append(DecisionLog.org_code == org_code)
    if profile_code is not None:
        where.append(DecisionLog.profile_code == profile_code)
    total = session.scalar(select(func.count()).select_from(DecisionLog).where(*where))
    rows = session.scalars(
        select(DecisionLog)
        .where(*where)
        .order_by(DecisionLog.created_at.desc(), DecisionLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return Page[Decision](items=[_decision(r) for r in rows], total=total, limit=limit, offset=offset)


# ------------------------------------------------------------------------------------------ alerts
def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def alerts(session: Session, region_code: str | None, limit: int, offset: int) -> Page[AlertItem]:
    info = build_info(session)
    cfg = info.config["alerts"]
    m = MartHospitalProfileStatus
    trend_alert = (
        m.has_sufficient_data
        & (m.queue_trend_4w >= cfg["queue_trend_min_pct"])
        & (m.queue_now >= cfg["queue_trend_min_queue_now"])
    )
    where = [or_(m.load_index >= cfg["load_index_min"], trend_alert)]
    if region_code is not None:
        require_region(session, region_code)
        where.append(m.region_code == region_code)
    total = session.scalar(select(func.count()).select_from(m).where(*where))
    rows = session.scalars(select(m).where(*where).order_by(*load_index_order()).limit(limit).offset(offset)).all()

    items = []
    for r in rows:
        reasons = []
        if r.load_index is not None and r.load_index >= cfg["load_index_min"]:
            backlog = f", очередь рассасывается за {_fmt(r.backlog_days)} дн." if r.backlog_days is not None else ""
            reasons.append(
                f"Индекс нагрузки {_fmt(r.load_index)} ≥ {_fmt(cfg['load_index_min'], 0)}: "
                f"место {r.region_rank} из {r.region_n_ranked} в регионе{backlog}"
            )
        if (
            r.has_sufficient_data
            and r.queue_trend_4w is not None
            and r.queue_trend_4w >= cfg["queue_trend_min_pct"]
            and r.queue_now >= cfg["queue_trend_min_queue_now"]
        ):
            median = r.queue_trend_raw_4w - r.queue_trend_4w
            reasons.append(
                f"Очередь растёт на {_fmt(r.queue_trend_raw_4w)}% в неделю за последние 4 недели — на "
                f"{_fmt(r.queue_trend_4w)} п.п. быстрее медианы по стране ({_fmt(median)}%); "
                f"сейчас {r.queue_now} чел."
            )
        items.append(
            AlertItem(
                region_code=r.region_code,
                region_name=r.region_name,
                org_code=r.org_code,
                org_name=r.org_name,
                profile_code=r.profile_code,
                profile_name=r.profile_name,
                load_index=rnd(r.load_index, 1),
                status=r.status,
                queue_now=r.queue_now,
                backlog_days=rnd(r.backlog_days, 1),
                queue_trend_raw_4w=rnd(r.queue_trend_raw_4w, 1),
                queue_trend_4w=rnd(r.queue_trend_4w, 1),
                refusal_rate_28d=rnd(r.refusal_rate_28d, 4),
                reasons=reasons,
            )
        )
    return Page[AlertItem](items=items, total=total, limit=limit, offset=offset)
