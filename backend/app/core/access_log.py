"""Access log: one `access_log` row per request under /api, written outside the request path.

Pure ASGI middleware (no response buffering). The auth dependency stores the caller in `request.state.principal`,
which lives in the ASGI scope, so the key label and role are known here after the endpoint ran; requests rejected
before authentication (401) are logged without them. `X-Request-ID` comes from `app.core.logging`, so a row can be
joined with the container log lines of the same call.

Why the write is not in the request path: the row used to be committed in a second database session while the
response was already finished, which meant two database sessions per request. Rows now go to a bounded queue that
one background task drains: it collects what arrives within FLUSH_INTERVAL_SECONDS (at most MAX_ROWS_PER_COMMIT
rows) and commits the batch through a single session, so a request opens one session, the audit write costs a
fraction of one, and no request waits for it. A row therefore appears in the table up to a quarter of a second
after the response. The queue is bounded on purpose: under a flood the audit write is what gets dropped (with a
warning that says how many), not the response.

What is recorded and what is not: the method, the path and a truncated query string (`?format=pdf&limit=…` — an
auditor asking "who exported what" needs it), never a request body. `client_ip` is the first `X-Forwarded-For`
entry only when the TCP peer is one of `TRUSTED_PROXY_CIDRS` (the docker bridge by default, where the only peer is
the UI's nginx); for any other peer the header can be forged, so the peer address itself is stored and the header
is kept verbatim in `forwarded_for`. CORS preflights (`OPTIONS`) are not logged — they carry no identity and no
data; `401`s are.

Retention is an open decision, not a promise: see docs/security.md §3.
"""

import asyncio
import ipaddress
import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.db.models import AccessLog
from app.db.session import ApiSessionLocal

logger = logging.getLogger("hqai.access_log")

MAX_QUEUED_ROWS = 2000
MAX_ROWS_PER_COMMIT = 100
FLUSH_INTERVAL_SECONDS = 0.25
QUERY_LIMIT = 500

TrustedNetworks = tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]


def trusted_networks(cidrs: list[str]) -> TrustedNetworks:
    """Parsed TRUSTED_PROXY_CIDRS; an unparsable entry is reported once and ignored."""
    networks = []
    for cidr in cidrs:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXY_CIDRS: %r is not a network, ignored", cidr)
    return tuple(networks)


def client_ip_for(peer: str | None, forwarded_for: str | None, networks: TrustedNetworks) -> str | None:
    """The address to hold the caller to: the first forwarded entry behind a trusted proxy, the TCP peer otherwise."""
    if not peer:
        return None
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return peer[:64]
    if forwarded_for and any(address in network for network in networks):
        first = forwarded_for.split(",")[0].strip()
        if first:
            return first[:64]
    return peer[:64]


def _write(rows: list[AccessLog]) -> None:
    try:
        with ApiSessionLocal() as session:
            session.add_all(rows)
            session.commit()
    except Exception:  # noqa: BLE001 — logging must never break a request
        logger.exception("could not write %d access_log row(s)", len(rows))


class AccessLogWriter:
    """Bounded queue plus the single task that drains it; started on the first request of the running loop."""

    def __init__(self, max_rows: int = MAX_QUEUED_ROWS) -> None:
        self.max_rows = max_rows
        self.dropped = 0
        self._queue: asyncio.Queue[AccessLog] | None = None
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def submit(self, row: AccessLog) -> None:
        queue = self._queue_on_this_loop()
        try:
            queue.put_nowait(row)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning("access_log queue full (%d rows): %d row(s) dropped", self.max_rows, self.dropped)

    async def drain(self, timeout: float = 10.0) -> None:
        """Wait until every queued row has been committed (shutdown and tests)."""
        if self._queue is None or self._queue.empty():
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout)
        except TimeoutError:
            logger.warning("access_log queue did not drain within %.1fs", timeout)

    def _queue_on_this_loop(self) -> asyncio.Queue[AccessLog]:
        loop = asyncio.get_running_loop()
        if self._queue is None or self._loop is not loop:
            self._queue = asyncio.Queue(maxsize=self.max_rows)
            self._loop = loop
            self._task = None
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._drain_forever(self._queue))
        return self._queue

    async def _drain_forever(self, queue: asyncio.Queue[AccessLog]) -> None:
        loop = asyncio.get_running_loop()
        while True:
            rows = [await queue.get()]
            deadline = loop.time() + FLUSH_INTERVAL_SECONDS
            while len(rows) < MAX_ROWS_PER_COMMIT:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                try:
                    rows.append(await asyncio.wait_for(queue.get(), remaining))
                except TimeoutError:
                    break
            try:
                await loop.run_in_executor(None, _write, rows)
            finally:
                for _ in rows:
                    queue.task_done()


writer = AccessLogWriter()


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp, path_prefix: str = "/api") -> None:
        self.app = app
        self.path_prefix = path_prefix
        self.networks = trusted_networks(get_settings().trusted_proxy_cidrs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.path_prefix) or scope["method"] == "OPTIONS":
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
            writer.submit(self._row(scope, status_code, round((time.perf_counter() - started) * 1000, 2)))

    def _row(self, scope: Scope, status_code: int, latency_ms: float) -> AccessLog:
        state = scope.get("state") or {}
        principal = state.get("principal")
        headers = dict(scope.get("headers") or [])
        forwarded = headers.get(b"x-forwarded-for")
        forwarded_for = forwarded.decode("latin-1") if forwarded else None
        client = scope.get("client")
        query = (scope.get("query_string") or b"").decode("latin-1")
        return AccessLog(
            key_label=principal.label if principal else None,
            role=principal.role if principal else None,
            method=scope["method"][:8],
            path=scope["path"][:2000],
            query=query[:QUERY_LIMIT] or None,
            status=status_code,
            latency_ms=latency_ms,
            client_ip=client_ip_for(client[0] if client else None, forwarded_for, self.networks),
            forwarded_for=forwarded_for[:500] if forwarded_for else None,
            request_id=state.get("request_id"),
        )
