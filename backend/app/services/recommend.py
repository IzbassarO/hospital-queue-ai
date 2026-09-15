"""Rule-based recommendations v1: alternative hospitals for an overloaded hospital × profile.

Rule (parameters from ml/configs/serving.yaml → mart_build_info.config.recommendations; docs/api.md):

1. Trigger: the hospital × profile has a load_index in the top `region_top_fraction` (20%) of its region
   (mart column in_region_top) and a defined backlog_days.
2. Candidates: other hospitals in the SAME region and the SAME profile with
   registrations_28d >= `min_registrations_28d` and backlog_days lower than the current one.
3. Effect: a `WaitEffectEstimator` estimates the expected wait at the current and the alternative hospital;
   candidates are kept when the estimated saving is >= `min_wait_delta_days` (3 days).
4. Up to `max_alternatives` (3), largest saving first.

The estimator is the swappable part. v1 (`HistoricalMedianEstimator`) uses the hospital × profile median
wait of the last 28 days — an association, not a causal effect. A causal module will provide another
implementation of the same protocol; nothing else in this module has to change.
"""
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import MartHospitalProfileStatus
from app.schemas.activity import Alternative, CurrentState, RecommendationResponse, RecommendationRule
from app.services.common import build_info, hospital_row, rnd

DISCLAIMER = (
    "Оценка основана на исторических медианах ожидания за последние 28 дней и не является причинным "
    "эффектом: перенаправление пациента не гарантирует такого сокращения ожидания. Решение принимает специалист."
)


@dataclass(frozen=True)
class WaitEstimate:
    expected_wait_current: float
    expected_wait_alternative: float

    @property
    def delta_days(self) -> float:
        return self.expected_wait_current - self.expected_wait_alternative


class WaitEffectEstimator(Protocol):
    """Estimates the expected wait for the same referral at the current vs an alternative hospital."""

    method: str

    def estimate(self, current: MartHospitalProfileStatus,
                 alternative: MartHospitalProfileStatus) -> WaitEstimate | None:
        """None when no estimate is possible for this pair."""
        ...


class HistoricalMedianEstimator:
    """v1: median wait of non-same-day hospitalizations of the last 28 days, per hospital × profile."""

    method = "historical_median"

    def estimate(self, current: MartHospitalProfileStatus,
                 alternative: MartHospitalProfileStatus) -> WaitEstimate | None:
        if current.median_wait_28d is None or alternative.median_wait_28d is None:
            return None
        return WaitEstimate(current.median_wait_28d, alternative.median_wait_28d)


def recommendation_id(current: MartHospitalProfileStatus, alternative: MartHospitalProfileStatus,
                      method: str) -> str:
    return (f"rec-v1:{method}:{current.as_of_date.isoformat()}:{current.org_code}:{current.profile_code}:"
            f"{alternative.org_code}")


def _num(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "нет данных"
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{value:.0f}"
    return text.replace(".", ",")


def _pct(value: float | None) -> str:
    return "нет данных" if value is None else f"{_num(value * 100, 1)}%"


def _days(value: float) -> str:
    n = abs(value)
    if n != int(n):
        return f"{_num(value)} дня"
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        word = "день"
    elif n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{_num(value, 0)} {word}"


def explanation_text(current: MartHospitalProfileStatus, alternative: MartHospitalProfileStatus,
                     estimate: WaitEstimate) -> str:
    return (
        f"В стационаре «{alternative.org_name}» ожидаемое время ожидания госпитализации по профилю "
        f"«{current.profile_name}» — {_days(estimate.expected_wait_alternative)} против "
        f"{_days(estimate.expected_wait_current)} в «{current.org_name}», то есть на "
        f"{_days(estimate.delta_days)} меньше (медиана за последние 28 дней). "
        f"Очередь рассасывается за {_num(alternative.backlog_days)} дн. против {_num(current.backlog_days)} дн., "
        f"доля отказов — {_pct(alternative.refusal_rate_28d)} против {_pct(current.refusal_rate_28d)}."
    )


def recommend(session: Session, org_code: str, profile_code: str,
              estimator: WaitEffectEstimator | None = None) -> RecommendationResponse:
    estimator = estimator or HistoricalMedianEstimator()
    info = build_info(session)
    rule_cfg = info.config["recommendations"]
    rule = RecommendationRule(**{k: rule_cfg[k] for k in RecommendationRule.model_fields})
    current = hospital_row(session, org_code, profile_code)

    alternatives: list[Alternative] = []
    reason: str | None = None
    eligible = bool(current.in_region_top and current.load_index is not None)
    if current.load_index is None:
        reason = "Недостаточно данных для индекса нагрузки (меньше 10 направлений за 28 дней)."
    elif not current.in_region_top:
        reason = (f"Индекс нагрузки {_num(current.load_index)} не входит в верхние "
                  f"{_num(rule.region_top_fraction * 100, 0)}% по региону (место {current.region_rank} "
                  f"из {current.region_n_ranked}); рекомендации не формируются.")
    elif current.backlog_days is None:
        reason = ("Срок рассасывания очереди не определён (меньше 0,5 госпитализации в день), "
                  "поэтому сравнить стационары по очереди нельзя.")
    else:
        m = MartHospitalProfileStatus
        candidates = session.scalars(
            select(m).where(
                m.region_code == current.region_code,
                m.profile_code == current.profile_code,
                m.org_code != current.org_code,
                m.registrations_28d >= rule.min_registrations_28d,
                m.backlog_days.is_not(None),
                m.backlog_days < current.backlog_days,
            )
        ).all()
        scored = []
        for alt in candidates:
            estimate = estimator.estimate(current, alt)
            if estimate is not None and estimate.delta_days >= rule.min_wait_delta_days:
                scored.append((alt, estimate))
        scored.sort(key=lambda pair: (-pair[1].delta_days, pair[0].backlog_days, pair[0].org_code))
        for alt, estimate in scored[: rule.max_alternatives]:
            alternatives.append(Alternative(
                recommendation_id=recommendation_id(current, alt, estimator.method),
                org_code=alt.org_code, org_name=alt.org_name, region_code=alt.region_code,
                profile_code=alt.profile_code,
                expected_wait_current=round(estimate.expected_wait_current, 1),
                expected_wait_alternative=round(estimate.expected_wait_alternative, 1),
                delta_days=round(estimate.delta_days, 1),
                refusal_rate_current=rnd(current.refusal_rate_28d, 4),
                refusal_rate_alternative=rnd(alt.refusal_rate_28d, 4),
                backlog_days_current=round(current.backlog_days, 1),
                backlog_days_alternative=round(alt.backlog_days, 1),
                load_index_alternative=rnd(alt.load_index, 1),
                registrations_28d_alternative=alt.registrations_28d,
                method=estimator.method,
                explanation=explanation_text(current, alt, estimate),
            ))
        if not alternatives:
            reason = (f"В регионе нет стационаров того же профиля с меньшей очередью, не менее "
                      f"{rule.min_registrations_28d} направлений за 28 дней и ожиданием короче минимум на "
                      f"{_days(rule.min_wait_delta_days)}.")

    return RecommendationResponse(
        as_of_date=info.as_of_date,
        region_code=current.region_code, region_name=current.region_name,
        org_code=current.org_code, org_name=current.org_name,
        profile_code=current.profile_code, profile_name=current.profile_name,
        method=estimator.method, eligible=eligible, reason=reason,
        current=CurrentState(
            load_index=rnd(current.load_index, 1), status=current.status, region_rank=current.region_rank,
            region_n_ranked=current.region_n_ranked, in_region_top=current.in_region_top,
            backlog_days=rnd(current.backlog_days, 1), median_wait_28d=rnd(current.median_wait_28d, 1),
            refusal_rate_28d=rnd(current.refusal_rate_28d, 4), registrations_28d=current.registrations_28d,
        ),
        rule=rule,
        alternatives=alternatives,
        disclaimer=DISCLAIMER,
    )
