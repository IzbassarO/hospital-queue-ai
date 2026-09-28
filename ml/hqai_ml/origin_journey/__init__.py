"""Origin-safe cohort construction for patient-journey models.

Only the training-safe API is exported here. Hindsight labels deliberately require
an explicit import from :mod:`hqai_ml.origin_journey.evaluation`.
"""

from hqai_ml.origin_journey.cohorts import OriginCohorts, build_origin_cohorts
from hqai_ml.origin_journey.config import OriginJourneyConfig, load_origin_journey_config
from hqai_ml.origin_journey.hashing import canonical_frame_sha256
from hqai_ml.origin_journey.time_grid import TimeInterval, build_time_grid

__all__ = [
    "OriginCohorts",
    "OriginJourneyConfig",
    "TimeInterval",
    "build_origin_cohorts",
    "build_time_grid",
    "canonical_frame_sha256",
    "load_origin_journey_config",
]
