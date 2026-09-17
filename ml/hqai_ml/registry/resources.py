"""Bounded local resource profiles for reproducible model training."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceConfig:
    profile: str
    detected_cpu_count: int
    model_threads: int
    parallel_trials: int
    process_concurrency: int


def resource_config(
    profile_name: str,
    *,
    cpu_count: int | None = None,
    model_threads: int | None = None,
    parallel_trials: int | None = None,
    process_concurrency: int | None = None,
) -> ResourceConfig:
    cpus = max(1, cpu_count or os.cpu_count() or 1)
    if profile_name == "laptop":
        defaults = (max(1, min(4, cpus // 2)), 1, 1)
    elif profile_name == "overnight":
        defaults = (max(1, min(8, cpus - 1)), max(1, min(2, cpus // 4)), max(1, min(2, cpus // 4)))
    else:
        raise ValueError(f"unknown resource profile {profile_name!r}")
    threads = model_threads if model_threads is not None else defaults[0]
    trials = parallel_trials if parallel_trials is not None else defaults[1]
    processes = process_concurrency if process_concurrency is not None else defaults[2]
    if threads < 1 or trials < 1 or processes < 1:
        raise ValueError("resource overrides must be positive")
    return ResourceConfig(profile_name, cpus, min(threads, cpus), min(trials, cpus), min(processes, cpus))


def apply_resource_environment(resources: ResourceConfig) -> None:
    value = str(resources.model_threads)
    names = (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    for name in names:
        os.environ[name] = value


def seed_process(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
