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
import uuid
from collections.abc import Awaitable, Callable, Mapping

from sqlalchemy import select
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.database import get_db_context
from app.models.csrf_token import CSRFToken
from app.utils.datetime_utils import utc_now

logger = logging.getLogger(__name__)


def is_test_mode() -> bool:
    """Check if running in test mode (disables CSRF validation)."""
    return os.getenv("MYGARAGE_TEST_MODE", "").lower() == "true"


_SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: "
            "https://tile.openstreetmap.org "
            "https://a.tile.openstreetmap.org "
            "https://b.tile.openstreetmap.org "
            "https://c.tile.openstreetmap.org "
            "https://cdnjs.cloudflare.com; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-src 'self' blob:; "
            "frame-ancestors 'self'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
        ),
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "SAMEORIGIN"),
    ("X-XSS-Protection", "1; mode=block"),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("Permissions-Policy", "geolocation=(), microphone=(), camera=()"),
)


class SecurityHeadersMiddleware:
    """Add security headers to all HTTP responses.

    Pure ASGI middleware so streaming responses are not buffered.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS:
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
