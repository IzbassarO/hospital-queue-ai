"""FastAPI application: /api/v1 (docs/api.md). Interactive docs at /docs."""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.access_log import AccessLogMiddleware
from app.core.config import get_settings
from app.core.security import API_KEY_HEADER
from app.services.assistant import AssistantNotConfiguredError, AssistantUpstreamError
from app.services.common import ConflictError, MartsNotBuiltError, NotFoundError, ValidationError
from app.services.export import ExportUnavailableError

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "Monitoring of planned-hospitalization queues and hospital load (GovTech Camp 2026, Case 1). "
        "Read-only except POST /decisions (human-in-the-loop record) and key management. Every endpoint except "
        f"/health needs an API key in the {API_KEY_HEADER} header (docs/security.md). "
        "Formulas and examples: docs/api.md."
    ),
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
# outermost: every /api request is logged, including CORS preflights and 401s
app.add_middleware(AccessLogMiddleware, path_prefix="/api")
app.include_router(router, prefix=settings.api_prefix)


@app.exception_handler(NotFoundError)
def _not_found(_: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
def _invalid(_: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
def _conflict(_: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


@app.exception_handler(ExportUnavailableError)
def _export_unavailable(_: Request, exc: ExportUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.exception_handler(MartsNotBuiltError)
def _not_built(_: Request, exc: MartsNotBuiltError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.get("/health", include_in_schema=False, operation_id="liveness_get")
def liveness() -> dict[str, str]:
    """Process liveness without touching the database (container healthcheck)."""
    return {"status": "ok"}


@app.exception_handler(AssistantNotConfiguredError)
def _assistant_not_configured(_: Request, exc: AssistantNotConfiguredError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)})


@app.exception_handler(AssistantUpstreamError)
def _assistant_upstream(_: Request, exc: AssistantUpstreamError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": str(exc)})
