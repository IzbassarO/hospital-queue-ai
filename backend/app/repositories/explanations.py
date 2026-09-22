"""Structured PostgreSQL retrieval for operational-signal explanations."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ModelAssuranceCapability,
    ModelAssuranceSnapshot,
    OperationalForecast,
    OperationalIntelligenceSnapshot,
    OperationalSignal,
)


@dataclass(frozen=True)
class SignalExplanationRows:
    snapshot: OperationalIntelligenceSnapshot
    signal: OperationalSignal
    forecast: OperationalForecast | None
    assurance: ModelAssuranceSnapshot | None
    capabilities: tuple[ModelAssuranceCapability, ...]


def signal_explanation(session: Session, signal_id: str) -> SignalExplanationRows | None:
    """Return bounded published rows for one signal; never reads ML artifacts."""
    snapshot = session.scalar(
        select(OperationalIntelligenceSnapshot).where(OperationalIntelligenceSnapshot.is_active.is_(True))
    )
    if snapshot is None:
        return None
    signal = session.scalar(
        select(OperationalSignal).where(
            OperationalSignal.snapshot_id == snapshot.id,
            OperationalSignal.signal_id == signal_id,
        )
    )
    if signal is None:
        return None

    forecast = None
    if signal.first_crossing_date is not None:
        forecast = session.scalar(
            select(OperationalForecast).where(
                OperationalForecast.snapshot_id == snapshot.id,
                OperationalForecast.series_id == signal.series_id,
                OperationalForecast.origin == signal.origin,
                OperationalForecast.target == signal.target,
                OperationalForecast.target_date == signal.first_crossing_date,
            )
        )

    assurance = session.scalar(
        select(ModelAssuranceSnapshot).where(
            ModelAssuranceSnapshot.assurance_identity_sha256 == snapshot.assurance_identity_sha256
        )
    )
    capabilities: tuple[ModelAssuranceCapability, ...] = ()
    if assurance is not None:
        capabilities = tuple(
            session.scalars(
                select(ModelAssuranceCapability)
                .where(ModelAssuranceCapability.snapshot_id == assurance.id)
                .order_by(ModelAssuranceCapability.capability_id)
            ).all()
        )
    return SignalExplanationRows(snapshot, signal, forecast, assurance, capabilities)
