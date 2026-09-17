"""API-key authentication and role checks (docs/security.md).

Keys are random 256-bit tokens (`hqai_<43 url-safe chars>`); only their SHA-256 is stored in `api_keys`, so a leaked
database does not reveal usable keys. A slow password hash (bcrypt/argon2) is unnecessary for random tokens of this
length. Roles are ordered: viewer (every GET) < specialist (+ POST /decisions) < admin (+ key management, access log).

Every endpoint except the health checks declares one of ViewerDep / SpecialistDep / AdminDep; tools/audit.py fails
when a route has none (the dependency functions carry the `__hqai_auth__` marker it looks for).
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ApiKey
from app.db.session import get_session

Role = Literal["viewer", "specialist", "admin"]
ROLES: tuple[Role, ...] = ("viewer", "specialist", "admin")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}
ROLE_LABELS = {"viewer": "наблюдатель", "specialist": "специалист", "admin": "администратор"}
API_KEY_HEADER = "X-API-Key"
API_KEY_SCHEME_NAME = "ApiKeyAuth"
KEY_PREFIX = "hqai_"
api_key_header = APIKeyHeader(
    name=API_KEY_HEADER,
    scheme_name=API_KEY_SCHEME_NAME,
    description="API key issued by hospital-queue-ai",
    auto_error=False,
)


@dataclass(frozen=True)
class Principal:
    key_id: int
    label: str
    role: Role


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def display_prefix(key: str) -> str:
    """First characters of a key, safe to show in lists and logs (not enough to use it)."""
    return key[: len(KEY_PREFIX) + 6]


def authenticate(session: Session, key: str | None) -> Principal | None:
    if not key:
        return None
    row = session.scalar(select(ApiKey).where(ApiKey.key_hash == hash_key(key), ApiKey.revoked_at.is_(None)))
    return Principal(key_id=row.id, label=row.label, role=row.role) if row else None


def require_role(minimum: Role):
    def dependency(
        request: Request,
        session: Annotated[Session, Depends(get_session)],
        x_api_key: Annotated[str | None, Security(api_key_header)],
    ) -> Principal:
        principal = authenticate(session, x_api_key)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing API key" if not x_api_key else "invalid or revoked API key",
                headers={"WWW-Authenticate": API_KEY_HEADER},
            )
        # read by the access-log middleware after the response
        request.state.principal = principal
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {principal.role!r} may not do this; requires {minimum!r} or higher",
            )
        return principal

    dependency.__hqai_auth__ = minimum  # type: ignore[attr-defined]
    dependency.__name__ = f"require_{minimum}"
    return dependency


ViewerDep = Annotated[Principal, Depends(require_role("viewer"))]
SpecialistDep = Annotated[Principal, Depends(require_role("specialist"))]
AdminDep = Annotated[Principal, Depends(require_role("admin"))]
