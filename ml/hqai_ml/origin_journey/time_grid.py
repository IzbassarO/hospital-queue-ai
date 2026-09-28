from __future__ import annotations

from dataclasses import dataclass

from hqai_ml.origin_journey.config import OriginJourneyConfig


@dataclass(frozen=True)
class TimeInterval:
    """A half-open duration interval ``[start_day, end_day)``."""

    index: int
    start_day: int
    end_day: int
    is_daily: bool


def build_time_grid(config: OriginJourneyConfig) -> tuple[TimeInterval, ...]:
    """Return daily duration bins through day 30, followed by configured coarse bins."""
    policy = config.time_grid
    edges = tuple(range(policy.daily_start_day, policy.daily_through_day + 1)) + policy.coarse_edges
    return tuple(
        TimeInterval(index=i, start_day=start, end_day=end, is_daily=(end - start == 1))
        for i, (start, end) in enumerate(zip(edges[:-1], edges[1:], strict=True))
    )
