"""Bounded local resource profiles for reproducible model training."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

MIB = 1024 * 1024
GIB = 1024 * MIB


@dataclass(frozen=True)
class ResourceConfig:
    profile: str
    detected_cpu_count: int
    cpu_budget: int
    model_threads: int
    parallel_trials: int
    process_concurrency: int
    detected_memory_bytes: int
    memory_budget_bytes: int
    duckdb_threads: int
    duckdb_memory_limit: str

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
    memory_bytes: int | None = None,
    duckdb_memory_mb: int | None = None,
) -> ResourceConfig:
    cpus = cpu_count if cpu_count is not None else os.cpu_count() or 1
    if cpus < 1:
        raise ValueError("detected CPU count must be positive")
    if profile_name == "smoke":
        budget, desired_threads, default_trials, default_processes = 1, 1, 1, 1
    elif profile_name == "laptop":
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
    detected_memory = memory_bytes if memory_bytes is not None else _physical_memory_bytes()
    if detected_memory < MIB:
        raise ValueError("detected memory must be at least 1 MiB")
    if profile_name == "smoke":
        memory_budget = min(detected_memory // 8, 512 * MIB)
    elif profile_name == "laptop":
        memory_budget = min(detected_memory // 4, 2 * GIB)
    else:
        memory_budget = min(detected_memory // 2, 4 * GIB)
    memory_budget = max(MIB, memory_budget)
    workers = trials * processes
    if duckdb_memory_mb is not None:
        if duckdb_memory_mb < 1:
            raise ValueError("DuckDB memory override must be positive")
        duckdb_bytes = duckdb_memory_mb * MIB
        if duckdb_bytes * workers > memory_budget:
            raise ValueError(
                "DuckDB memory override exceeds the profile memory budget across concurrent workers: "
                f"{duckdb_memory_mb} MiB × {workers} > {memory_budget // MIB} MiB"
            )
    else:
        duckdb_bytes = max(MIB, memory_budget // workers)
    duckdb_mib = max(1, duckdb_bytes // MIB)
    return ResourceConfig(
        profile_name,
        cpus,
        budget,
        threads,
        trials,
        processes,
        detected_memory,
        memory_budget,
        threads,
        f"{duckdb_mib}MiB",
    )


def _physical_memory_bytes() -> int:
    """Portable best effort without a runtime dependency; the fallback remains conservative."""
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        if page_size > 0 and pages > 0:
            return page_size * pages
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    return 4 * GIB


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
