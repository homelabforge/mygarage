"""Security middleware for MyGarage application.

These are written as pure ASGI middleware rather than Starlette's
`BaseHTTPMiddleware` because the latter buffers the entire response
body through an internal asyncio queue before forwarding it. That
defeats streaming responses (e.g. `FileResponse` for photos and
backup downloads) and produced the bursty 20 KB/s download pattern
we measured for `/api/backup/download/<file>`. Pure ASGI middleware
wraps `send` directly and only inspects the headers message — the
response body streams through untouched.
"""

import json
import logging
import os
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

from sqlalchemy import select
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.database import get_db_context
from app.models.csrf_token import CSRFToken
from app.utils.datetime_utils import utc_now
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)


def is_test_mode() -> bool:
    """Check if running in test mode (disables CSRF validation)."""
    return os.getenv("MYGARAGE_TEST_MODE", "").lower() == "true"


def _content_security_policy(script_hashes: Sequence[str]) -> str:
    """The CSP, with the SPA shell's inline scripts allowed by hash.

    ``script-src`` stays ``'self'`` plus the hashes of the inline scripts the
    served index.html carries (``html_base.inline_script_hashes``): no
    ``'unsafe-inline'``, and no nonce to thread through a cached shell.
    """
    script_src = " ".join(("'self'", *(f"'{h}'" for h in script_hashes)))
    return (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: "
        "https://tile.openstreetmap.org "
        "https://a.tile.openstreetmap.org "
        "https://b.tile.openstreetmap.org "
        "https://c.tile.openstreetmap.org "
        "https://cdnjs.cloudflare.com "
        "https://cdn.jsdelivr.net "
        "https://raw.githubusercontent.com; "
        "font-src 'self'; "
        "connect-src 'self' https://vpic.nhtsa.dot.gov; "
        "frame-src 'self' blob:; "
        "frame-ancestors 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
    )


_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "SAMEORIGIN"),
    ("X-XSS-Protection", "1; mode=block"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
)


class SecurityHeadersMiddleware:
    """Add security headers to all HTTP responses.

    Pure ASGI middleware so streaming responses are not buffered.
    ``script_hashes`` are the CSP sources for the shell's inline scripts.
    """

    def __init__(self, app: ASGIApp, script_hashes: Sequence[str] = ()) -> None:
        self.app = app
        self._headers = (
            ("Content-Security-Policy", _content_security_policy(script_hashes)),
            *_SECURITY_HEADERS,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in self._headers:
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class RequestIDMiddleware:
    """Tag each request with a unique ID and echo it back as a header.

    Pure ASGI middleware so streaming responses are not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())
        state = scope.setdefault("state", {})
        # FastAPI's Request.state reads from scope["state"], which can be a
        # dict or a State instance. Support both by mutating the underlying
        # container.
        if isinstance(state, dict):
            state["request_id"] = request_id
        else:
            state.request_id = request_id  # type: ignore[attr-defined]

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class CSRFProtectionMiddleware:
    """CSRF protection using the synchronizer token pattern.

    Validates CSRF tokens on state-changing operations (POST/PUT/PATCH/DELETE).
    Tokens are generated on login and validated against the database.

    Exempt routes:
    - /api/auth/login (token generation happens here)
    - /api/auth/oidc/* (OIDC flow has its own state protection)
    - /api/health (public health check)
    - /api/backup/* (protected by JWT auth, idempotent operations)
    - /api/settings/batch (user preferences, protected by JWT auth)
    - GET/HEAD/OPTIONS (safe methods)

    Pure ASGI middleware so the response body is not buffered.
    """

    EXEMPT_PATHS = (
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/logout",
        "/api/auth/oidc/",
        "/api/health",
        "/api/settings/public",
        "/api/backup/",
        "/api/settings/batch",
        "/api/v1/livelink/ingest",
        # Inbound webhooks (Home Assistant, n8n, Telegram) authenticate with the
        # shared webhook_ingest_token header. No browser session, no CSRF token,
        # exactly like the livelink ingest path above.
        "/api/v1/webhooks/",
    )

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if is_test_mode():
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        if method in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            await self.app(scope, receive, send)
            return

        # If auth is disabled, skip CSRF validation entirely.
        try:
            from app.services.auth import get_auth_mode

            async with get_db_context() as db:
                auth_mode = await get_auth_mode(db)
                if auth_mode == "none":
                    await self.app(scope, receive, send)
                    return
        except Exception:
            # If we can't determine auth mode, fall through to validation.
            pass

        csrf_token = _get_header(scope, b"x-csrf-token")
        if not csrf_token:
            await _send_json(
                send,
                status=403,
                payload={
                    "detail": ("CSRF token missing. Include X-CSRF-Token header with your request.")
                },
            )
            return

        try:
            async with get_db_context() as db:
                result = await db.execute(
                    select(CSRFToken).where(
                        CSRFToken.token == csrf_token,
                        CSRFToken.expires_at > utc_now(),
                    )
                )
                token_record = result.scalar_one_or_none()

                if token_record is None:
                    await _send_json(
                        send,
                        status=403,
                        payload={"detail": ("Invalid or expired CSRF token. Please login again.")},
                    )
                    return

                state = scope.setdefault("state", {})
                if isinstance(state, dict):
                    state["csrf_validated_user_id"] = token_record.user_id
                else:
                    state.csrf_validated_user_id = token_record.user_id  # type: ignore[attr-defined]
        except Exception as e:
            logger.error("CSRF validation error: %s", e, exc_info=True)
            await _send_json(
                send,
                status=500,
                payload={"detail": "Internal server error"},
            )
            return

        await self.app(scope, receive, send)


#: LiveLink ingest body-size cap. WiCAN AutoPID payloads are KB-scale; this is a
#: generous ceiling that still rejects an oversized/abusive POST before it reaches
#: the (linear-time) normalizer. An optional Traefik `maxRequestBodyBytes` cap is
#: documented as deploy-side defense-in-depth but is not in this repo (R1-H3).
INGEST_PATH = "/api/v1/livelink/ingest"

#: Router prefixes whose handlers write telemetry. Maintenance mode closes these
#: and nothing else: the rest of the API stays reachable so an operator can watch
#: the upgrade, and /api/health keeps answering so the container healthcheck does
#: not fail the maintenance window and trigger a restart.
#: Ingest routers, closed wholesale: everything under them writes telemetry.
MAINTENANCE_CLOSED_PREFIXES = ("/api/v1/livelink", "/api/v1/torque")

#: Individual admin routes that write telemetry. The admin router as a whole
#: must stay OPEN -- the operator uses it to watch the repair and to turn
#: maintenance mode back off -- so these are matched exactly rather than by
#: prefix. `POST /api/livelink/devices/{id}/backfill` reaches `bulk_backfill`.
_MAINTENANCE_CLOSED_ADMIN_RE = re.compile(r"^/api/livelink/devices/[^/]+/backfill/?$")


def is_maintenance_closed(path: str) -> bool:
    """Whether maintenance mode should refuse a request to ``path``.

    Args:
        path: The request path, without query string.

    Returns:
        True if the path can write telemetry and must be refused with 503.
    """
    if path.startswith(MAINTENANCE_CLOSED_PREFIXES):
        return True
    return _MAINTENANCE_CLOSED_ADMIN_RE.match(path) is not None


INGEST_MAX_BODY_BYTES = 256 * 1024


class IngestBodySizeLimitMiddleware:
    """Reject oversized POSTs to the LiveLink ingest endpoint with a 413.

    Pure ASGI middleware scoped to ``INGEST_PATH``. Uses the ``Content-Length``
    header as a fast path; for chunked / no-Content-Length requests it buffers
    the body (ingest payloads are small) and aborts once the cap is exceeded,
    then replays the buffered body to the inner app.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != INGEST_PATH:
            await self.app(scope, receive, send)
            return

        content_length = _get_header(scope, b"content-length")
        if content_length is not None:
            try:
                if int(content_length) > INGEST_MAX_BODY_BYTES:
                    await _send_json(
                        send,
                        status=413,
                        payload={"detail": "Request body too large"},
                    )
                    return
            except ValueError:
                pass  # Malformed Content-Length -> fall through to byte counting.

        # Buffer the body, aborting if it exceeds the cap (covers chunked uploads
        # and a lying/absent Content-Length).
        body = b""
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                # e.g. http.disconnect -- hand control back to the app.
                await self.app(scope, _single_message_receive(message, receive), send)
                return
            body += message.get("body", b"")
            more_body = message.get("more_body", False)
            if len(body) > INGEST_MAX_BODY_BYTES:
                await _send_json(
                    send,
                    status=413,
                    payload={"detail": "Request body too large"},
                )
                return

        await self.app(scope, _replay_body_receive(body, receive), send)


def _replay_body_receive(body: bytes, receive: Receive) -> Receive:
    """Return a receive() that yields the buffered body once, then defers."""
    sent = False

    async def _receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    return _receive


def _single_message_receive(first: Message, receive: Receive) -> Receive:
    """Return a receive() that replays one already-read message, then defers."""
    sent = False

    async def _receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return first
        return await receive()

    return _receive


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Look up a request header value (case-insensitive) from the ASGI scope."""
    name_lower = name.lower()
    for key, value in scope.get("headers", []):
        if key.lower() == name_lower:
            return value.decode("latin-1")
    return None


class MaintenanceModeMiddleware:
    """Refuse telemetry ingest with 503 while the instance is in maintenance mode.

    The upgrade procedure for the odometer repair tools requires that no new
    reading lands between the migration and the repair. Migrations run inside
    this app's own lifespan and the MQTT toggle is a database row, so stopping
    ingest from outside the process is not possible; this closes it from inside.

    ``settings.maintenance_mode`` is read per request rather than captured at
    construction, so the gate can be flipped in tests without rebuilding the app.
    The cost is one attribute read per request on a boolean that is almost always
    False.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from app.config import settings

        if scope["type"] != "http" or not settings.maintenance_mode:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not is_maintenance_closed(path):
            await self.app(scope, receive, send)
            return

        logger.info("Maintenance mode: refused ingest request to %s", path)
        await _send_json(
            send,
            status=503,
            payload={
                "detail": (
                    "MyGarage is in maintenance mode and is not accepting telemetry. "
                    "Readings buffered on the device will be delivered once it exits."
                )
            },
        )


_FORWARDED_FOR = b"x-forwarded-for"
_PROXY_HEADERS = frozenset({_FORWARDED_FOR, b"x-forwarded-proto", b"x-forwarded-host"})

# [v6] and [v6]:port, and a.b.c.d:port. Anything else goes to ip_address as written.
_BRACKETED_ADDRESS = re.compile(r"\[([^\]]*)\](?::[0-9]{1,5})?")
_IPV4_WITH_PORT = re.compile(r"([^:]*):[0-9]{1,5}")


def _parse_address(text: str) -> IPv4Address | IPv6Address | None:
    """Parse a peer or forwarded address, dropping any port, brackets or zone id.

    IPv4-mapped IPv6 comes back as IPv4. Returns None for anything that isn't
    an address, and never raises.
    """
    # This chews on whatever the client wrote, so any exception at all is just
    # junk, not a 500.
    try:
        value = text.strip()
        addr: IPv4Address | IPv6Address
        if bracketed := _BRACKETED_ADDRESS.fullmatch(value):
            addr = IPv6Address(bracketed.group(1))
        elif with_port := _IPV4_WITH_PORT.fullmatch(value):
            addr = IPv4Address(with_port.group(1))
        else:
            addr = ip_address(value)
        if isinstance(addr, IPv6Address):
            if addr.ipv4_mapped is not None:
                return addr.ipv4_mapped
            # Rebuilding from the int drops the zone id.
            return IPv6Address(int(addr))
        return addr
    except Exception:
        return None


def _is_trusted(
    addr: IPv4Address | IPv6Address, networks: Sequence[IPv4Network | IPv6Network]
) -> bool:
    """Whether ``addr`` is in one of the trusted networks."""
    return any(addr in net for net in networks)


def _peer_address(scope: Scope) -> IPv4Address | IPv6Address | None:
    """The connecting peer, or None when there's no client or it isn't an IP."""
    client = scope.get("client")
    return _parse_address(client[0]) if client else None


def _header_values(headers: Sequence[tuple[bytes, bytes]], name: bytes) -> list[bytes]:
    """Every value of header ``name`` (lowercase), compared case-insensitively."""
    return [value for key, value in headers if key.lower() == name]


def _walk_forwarded_for(
    values: Sequence[bytes], networks: Sequence[IPv4Network | IPv6Network]
) -> IPv4Address | IPv6Address | None:
    """The client from X-Forwarded-For: the first untrusted hop from the right.

    Junk ends the walk with no answer rather than getting skipped, since
    skipping it would let a client-written entry past a trusted proxy's.
    """
    joined = b",".join(values).decode("latin-1")
    entries = [entry.strip() for entry in joined.split(",") if entry.strip()]
    addr: IPv4Address | IPv6Address | None = None
    for entry in reversed(entries):
        addr = _parse_address(entry)
        if addr is None or not _is_trusted(addr, networks):
            return addr
    # Every hop was trusted, so the leftmost one is the client.
    return addr


class TrustedProxyMiddleware:
    """Set the ASGI client to the real one when a trusted proxy says who it is.

    A peer in ``settings.trusted_proxies`` gets its configured client IP header
    or its X-Forwarded-For believed. Anyone else has those headers stripped, so
    nothing downstream can be fooled by them. With no trusted proxies at all,
    nothing changes.

    Settings are read per request, like ``MaintenanceModeMiddleware``, so tests
    can flip them without rebuilding the app. Pure ASGI so streaming responses
    are not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        # One shot each. No await between the check and the set, so one event
        # loop can't log twice.
        self._warned_unconfigured = False
        self._warned_dropped = False
        self._warned_nothing_forwarded = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        from app.config import settings

        if scope["type"] in ("http", "websocket"):
            self._resolve_client(scope, settings.trusted_proxies, settings.client_ip_header)
        await self.app(scope, receive, send)

    def _resolve_client(
        self,
        scope: Scope,
        networks: Sequence[IPv4Network | IPv6Network],
        client_ip_header: str,
    ) -> None:
        """Rewrite ``scope`` in place: Granian's access log reads the same dict afterwards."""
        if not networks:
            # The default setup, so once this has fired there's nothing left to look at.
            if not self._warned_unconfigured and _get_header(scope, _FORWARDED_FOR) is not None:
                self._warned_unconfigured = True
                peer = _peer_address(scope)
                logger.warning(
                    "Got X-Forwarded-For from %s, but MYGARAGE_TRUSTED_PROXIES is empty, so rate "
                    "limits and audit logs see that address as the client. If it's your reverse "
                    "proxy, set MYGARAGE_TRUSTED_PROXIES to it (see Reverse-Proxy in the wiki). "
                    "Logged once.",
                    sanitize_for_log(str(peer) if peer is not None else "unknown"),
                )
            return

        peer = _peer_address(scope)
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or ())
        header_name = client_ip_header.encode("latin-1")

        if peer is None or not _is_trusted(peer, networks):
            dropped = (_PROXY_HEADERS | {header_name}) if header_name else _PROXY_HEADERS
            kept = [(name, value) for name, value in headers if name.lower() not in dropped]
            # A new list, never an edit of the server's.
            scope["headers"] = kept
            if len(kept) != len(headers) and not self._warned_dropped:
                self._warned_dropped = True
                logger.warning(
                    "Dropped proxy headers from %s, which isn't in MYGARAGE_TRUSTED_PROXIES. If "
                    "it's your reverse proxy, add it. Logged once.",
                    sanitize_for_log(str(peer) if peer is not None else "unknown"),
                )
            return

        forwarded_for = _header_values(headers, _FORWARDED_FOR)
        client_ips = _header_values(headers, header_name) if header_name else []
        if not forwarded_for and not client_ips and not self._warned_nothing_forwarded:
            self._warned_nothing_forwarded = True
            logger.warning(
                "Trusted proxy %s sent no X-Forwarded-For or client IP header, so rate limits and "
                "audit logs see it as the client. If it's your reverse proxy, have it send "
                "X-Forwarded-For (see Reverse-Proxy in the wiki); if it's a service calling "
                "MyGarage directly, ignore this. Logged once.",
                sanitize_for_log(str(peer)),
            )

        # Two copies of the client IP header means something appended instead of
        # replacing, and there's no telling which one the trusted layer wrote.
        addr = _parse_address(client_ips[0].decode("latin-1")) if len(client_ips) == 1 else None
        if addr is None:
            addr = _walk_forwarded_for(forwarded_for, networks)
        if addr is not None:
            # Headers stay put, so request_scheme still sees the proxy's Proto and Host.
            scope["client"] = (str(addr), 0)


def log_proxy_settings() -> None:
    """Log at startup who MyGarage takes the client's address from."""
    from app.config import settings

    if settings.trusted_proxies:
        logger.info(
            "Trusting proxy headers from %s; client IP header: %s",
            ", ".join(str(net) for net in settings.trusted_proxies),
            settings.client_ip_header or "none, using X-Forwarded-For",
        )
    elif settings.client_ip_header:
        logger.warning(
            "MYGARAGE_CLIENT_IP_HEADER is set but MYGARAGE_TRUSTED_PROXIES is empty, so it's ignored"
        )


async def _send_json(send: Send, *, status: int, payload: Mapping[str, object]) -> None:
    """Emit a JSON response from inside ASGI middleware without recursing.

    We assemble the ASGI messages by hand rather than calling a Starlette
    Response, because instantiating one inside middleware requires a fuller
    scope than we want to fabricate and creates a needless second layer.
    """
    body = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# Keep the symbol so dynamic imports don't break.
RequestResponseEndpoint = Callable[..., Awaitable[None]]
