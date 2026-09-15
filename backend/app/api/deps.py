"""Shared dependencies of the routers."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_session

SessionDep = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(ge=1, le=500, description="page size")] = 50,
    offset: Annotated[int, Query(ge=0, description="rows to skip")] = 0,
) -> Pagination:
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]
