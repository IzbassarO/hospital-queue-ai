"""API key management and the access log (admin endpoints and the `app.cli` commands)."""

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import Role, display_prefix, generate_key, hash_key
from app.db.models import AccessLog, ApiKey
from app.schemas.admin import AccessLogItem, ApiKeyCreated, ApiKeyInfo
from app.schemas.common import Page
from app.services.common import NotFoundError


def _info(row: ApiKey) -> ApiKeyInfo:
    return ApiKeyInfo(
        id=row.id,
        key_prefix=row.key_prefix,
        role=row.role,
        label=row.label,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


def create_key(session: Session, role: Role, label: str, key: str | None = None) -> ApiKeyCreated:
    """Store a new key (random unless `key` is given, e.g. the demo key from .env) and return it once."""
    key = key or generate_key()
    row = ApiKey(key_hash=hash_key(key), key_prefix=display_prefix(key), role=role, label=label)
    session.add(row)
    session.commit()
    session.refresh(row)
    return ApiKeyCreated(**_info(row).model_dump(), key=key)


def ensure_key(session: Session, key: str, role: Role, label: str) -> tuple[ApiKeyInfo, bool]:
    """Idempotent seeding: (key, created). An existing row with this key keeps its id; role and label are updated
    and a revoked key is NOT re-activated (revocation wins over seeding)."""
    row = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(key)))
    if row is None:
        created = create_key(session, role, label, key)
        return ApiKeyInfo(**created.model_dump(exclude={"key"})), True
    row.role, row.label = role, label
    session.commit()
    return _info(row), False


def list_keys(session: Session, include_revoked: bool = True) -> list[ApiKeyInfo]:
    query = select(ApiKey).order_by(ApiKey.created_at.desc(), ApiKey.id.desc())
    if not include_revoked:
        query = query.where(ApiKey.revoked_at.is_(None))
    return [_info(r) for r in session.scalars(query).all()]


def revoke_key(session: Session, key_id: int) -> ApiKeyInfo:
    row = session.get(ApiKey, key_id)
    if row is None:
        raise NotFoundError(f"unknown API key id {key_id}")
    if row.revoked_at is None:
        row.revoked_at = dt.datetime.now(dt.UTC)
        session.commit()
    return _info(row)


def access_log(
    session: Session, key_label: str | None, status: int | None, limit: int, offset: int
) -> Page[AccessLogItem]:
    where = []
    if key_label is not None:
        where.append(AccessLog.key_label == key_label)
    if status is not None:
        where.append(AccessLog.status == status)
    total = session.scalar(select(func.count()).select_from(AccessLog).where(*where))
    rows = session.scalars(
        select(AccessLog).where(*where).order_by(AccessLog.ts.desc(), AccessLog.id.desc()).limit(limit).offset(offset)
    ).all()
    items = [
        AccessLogItem(
            id=r.id,
            ts=r.ts,
            key_label=r.key_label,
            role=r.role,
            method=r.method,
            path=r.path,
            status=r.status,
            latency_ms=r.latency_ms,
            client_ip=r.client_ip,
            forwarded_for=r.forwarded_for,
        )
        for r in rows
    ]
    return Page[AccessLogItem](items=items, total=total, limit=limit, offset=offset)
