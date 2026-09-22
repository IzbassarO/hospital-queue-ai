"""Queries for the published Model Assurance read model."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ModelAssuranceCapability, ModelAssuranceSnapshot


def current_snapshot(session: Session, *, for_update: bool = False) -> ModelAssuranceSnapshot | None:
    query = select(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.is_active.is_(True))
    if for_update:
        query = query.with_for_update()
    return session.scalar(query)


def snapshot_by_assurance_id(session: Session, assurance_id: str) -> ModelAssuranceSnapshot | None:
    return session.scalar(select(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.assurance_id == assurance_id))


def snapshot_by_identity(session: Session, identity: str) -> ModelAssuranceSnapshot | None:
    return session.scalar(
        select(ModelAssuranceSnapshot).where(ModelAssuranceSnapshot.assurance_identity_sha256 == identity)
    )


def capabilities(session: Session, snapshot_id: int) -> list[ModelAssuranceCapability]:
    return list(
        session.scalars(
            select(ModelAssuranceCapability)
            .where(ModelAssuranceCapability.snapshot_id == snapshot_id)
            .order_by(ModelAssuranceCapability.capability_id)
        ).all()
    )


def capability(session: Session, snapshot_id: int, capability_id: str) -> ModelAssuranceCapability | None:
    return session.scalar(
        select(ModelAssuranceCapability).where(
            ModelAssuranceCapability.snapshot_id == snapshot_id,
            ModelAssuranceCapability.capability_id == capability_id,
        )
    )
