"""Bounded local resource profiles for reproducible model training."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceConfig:
    profile: str
    detected_cpu_count: int
    cpu_budget: int
    model_threads: int
    parallel_trials: int
    process_concurrency: int

    @property
    def requested_cpu_slots(self) -> int:
        return self.model_threads * self.parallel_trials * self.process_concurrency


def resource_config(
    profile_name: str,
    *,
    cpu_count: int | None = None,
    model_threads: int | None = None,
    parallel_trials: int | None = None,
    process_concurrency: int | None = None,
) -> ResourceConfig:
    cpus = cpu_count if cpu_count is not None else os.cpu_count() or 1
    if cpus < 1:
        raise ValueError("detected CPU count must be positive")
    if profile_name == "laptop":
        budget, desired_threads, default_trials, default_processes = max(1, cpus // 2), 4, 1, 1
    elif profile_name == "overnight":
        budget = max(1, cpus - 1)
        desired_threads, default_trials, default_processes = 8, min(2, budget), 1
    else:
        raise ValueError(f"unknown resource profile {profile_name!r}")
    trials = parallel_trials if parallel_trials is not None else default_trials
    processes = process_concurrency if process_concurrency is not None else default_processes
    if trials < 1 or processes < 1:
        raise ValueError("resource overrides must be positive")
    if trials * processes > budget:
        raise ValueError(
            "resource overrides oversubscribe the CPU budget even at one model thread: "
            f"{trials} trials × {processes} processes > {budget}"
        )
    remaining = budget // (trials * processes)
    threads = model_threads if model_threads is not None else min(desired_threads, remaining)
    if threads < 1:
        raise ValueError("resource overrides must be positive")
    requested = threads * trials * processes
    if requested > budget:
        raise ValueError(
            "resource overrides oversubscribe the CPU budget: "
            f"{threads} threads × {trials} trials × {processes} processes = {requested} > {budget}"
        )
    return ResourceConfig(profile_name, cpus, budget, threads, trials, processes)


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
