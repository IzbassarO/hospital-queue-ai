"""Application logging: one JSON object per line on stdout, every line carrying the id of the request that caused it.

Why JSON: a container log is read by `docker compose logs` during the demo and by a log collector in a real
deployment; one object per line is the format both can parse, and it needs no dependency beyond the standard
library (`logging.config.dictConfig` plus `json.dumps`).

Why request ids: `RequestIdMiddleware` takes the caller's `X-Request-ID` when it sends one of the allowed shape
(so an integrating system can correlate its own trace with ours) and generates one otherwise, echoes it on the
response, stores it in the ASGI scope for `app.core.access_log` — which writes it into the `access_log` row — and
publishes it in a context variable that `RequestIdFilter` copies onto every log record produced while that request
is handled, including records from the worker thread a sync endpoint runs in. Lines logged outside a request
(startup, the access-log writer) carry an empty `request_id`.

`LOG_LEVEL` in `.env` sets the level; uvicorn's own loggers are attached to the same handler so that a deployment
collects one format instead of three.
"""

import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from logging.config import dictConfig

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_SHAPE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
request_id_var: ContextVar[str] = ContextVar("hqai_request_id", default="")


def request_id_for(scope: Scope) -> str:
    """The caller's X-Request-ID if it is well-formed, otherwise a new one."""
    headers = dict(scope.get("headers") or [])
    supplied = headers.get(REQUEST_ID_HEADER.lower().encode("latin-1"), b"").decode("latin-1")
    return supplied if REQUEST_ID_SHAPE.match(supplied) else uuid.uuid4().hex


class RequestIdFilter(logging.Filter):
    """Copies the current request id onto the record so the formatter can render it."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", ""):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """One line, one JSON object: time, level, logger, message, request id, and the traceback when there is one."""

    converter = staticmethod(time.gmtime)
    default_time_format = "%Y-%m-%dT%H:%M:%S"
    default_msec_format = "%s.%03dZ"

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", ""),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Send every logger to stdout as JSON. Called once by app.main; an unknown level falls back to INFO."""
    wanted = level.strip().upper()
    if wanted not in logging.getLevelNamesMapping():
        wanted = "INFO"
    handlers = ["stdout"]
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                    "formatter": "json",
                    "filters": ["request_id"],
                }
            },
            "root": {"handlers": handlers, "level": wanted},
            "loggers": {
                name: {"handlers": handlers, "level": wanted, "propagate": False}
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
        }
    )


class RequestIdMiddleware:
    """Pure ASGI middleware: one request id per request, echoed on the response and visible to every log record."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_for(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, _echoing(send, request_id))
        finally:
            request_id_var.reset(token)


def _echoing(send: Send, request_id: str) -> Callable[[Message], Awaitable[None]]:
    async def send_with_request_id(message: Message) -> None:
        if message["type"] == "http.response.start":
            header = (REQUEST_ID_HEADER.lower().encode("latin-1"), request_id.encode("latin-1"))
            message["headers"] = [*message.get("headers", []), header]
        await send(message)

    return send_with_request_id
