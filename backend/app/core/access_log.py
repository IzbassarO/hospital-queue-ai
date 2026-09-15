"""Access log: one `access_log` row per request under /api, written after the response is sent.

Pure ASGI middleware (no response buffering). The auth dependency stores the caller in `request.state.principal`,
which lives in the ASGI scope, so the key label and role are known here after the endpoint ran; requests rejected
before authentication (401) are logged without them. A failure to write the log is reported to the server log and
never changes the response.
"""

import logging
import time

from anyio import to_thread
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.db.models import AccessLog
from app.db.session import SessionLocal

logger = logging.getLogger("hqai.access_log")


def _write(row: AccessLog) -> None:
    try:
        with SessionLocal() as session:
            session.add(row)
            session.commit()
    except Exception:  # noqa: BLE001 — logging must never break a request
        logger.exception("could not write access_log row for %s %s", row.method, row.path)


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp, path_prefix: str = "/api") -> None:
        self.app = app
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            principal = scope.get("state", {}).get("principal")
            headers = dict(scope.get("headers") or [])
            forwarded = headers.get(b"x-forwarded-for")
            client = scope.get("client")
            row = AccessLog(
                key_label=principal.label if principal else None,
                role=principal.role if principal else None,
                method=scope["method"][:8],
                path=scope["path"][:2000],
                status=status_code,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                client_ip=client[0][:64] if client else None,
                forwarded_for=forwarded.decode("latin-1")[:500] if forwarded else None,
            )
            await to_thread.run_sync(_write, row)
