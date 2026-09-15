"""FastAPI application: /api/v1 (docs/api.md). Interactive docs at /docs."""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.services.common import MartsNotBuiltError, NotFoundError, ValidationError

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Monitoring of planned-hospitalization queues and hospital load (GovTech Camp 2026, Case 1). "
        "Read-only except POST /decisions (human-in-the-loop record). Formulas and examples: docs/api.md."
    ),
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(router, prefix=settings.api_prefix)


@app.exception_handler(NotFoundError)
def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
def _invalid(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)})


@app.exception_handler(MartsNotBuiltError)
def _not_built(_: Request, exc: MartsNotBuiltError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.get("/health", include_in_schema=False)
def liveness() -> dict[str, str]:
    """Process liveness without touching the database (container healthcheck)."""
    return {"status": "ok"}
