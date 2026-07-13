"""Main FastAPI application for MyGarage."""

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.database import init_db


def _configure_logging() -> None:
    """Configure root logging.

    When MYGARAGE_LOG_PRETTY is truthy, use Rich with a layout that matches
    the tidewatch / vulnforge pretty-log look: time-only prefix (Docker adds
    the date in its log driver), colored level, no logger-name column, no
    wrapping. Otherwise fall back to the plain machine-friendly format
    suitable for log aggregators.
    """
    level = logging.DEBUG if settings.debug else logging.INFO
    pretty = os.getenv("MYGARAGE_LOG_PRETTY", "false").lower() in ("true", "1", "yes")

    handlers: list[logging.Handler]
    fmt: str
    if pretty:
        try:
            from rich.console import Console
            from rich.logging import RichHandler

            # Force a wide console so long log lines don't wrap to multiple
            # rows. Docker's log capture reports the terminal width as 80
            # which makes Rich fold messages aggressively.
            console = Console(
                width=240,
                force_terminal=True,
                no_color=False,
                highlight=False,
            )
            handlers = [
                RichHandler(
                    console=console,
                    rich_tracebacks=True,
                    show_path=False,
                    omit_repeated_times=False,
                    markup=False,
                    log_time_format="[%X]",
                )
            ]
            # Rich already shows time + level columns; we deliberately drop
            # the logger name so the output mirrors tidewatch's compact
            # `[HH:MM:SS] LEVEL  message` shape.
            fmt = "%(message)s"
        except ImportError:
            handlers = [logging.StreamHandler()]
            fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    else:
        handlers = [logging.StreamHandler()]
        fmt = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)


_configure_logging()
logger = logging.getLogger(__name__)


# Match a Granian access log line and capture the request path and status code.
# Granian's default access format is similar to the Apache combined format:
#   <client> [<date>] "<method> <path>[?query] HTTP/x" <status> <bytes>
# Anchoring the path before ? or whitespace prevents `/health` from matching
# `/health-status`, and the status capture lets us still surface failures
# (>=400) when the liveness check is misbehaving.
_ACCESS_LOG_PATTERN = re.compile(
    r'"(?:GET|HEAD|POST|PUT|DELETE|PATCH|OPTIONS)\s+'
    r"(?P<path>[^\s?]+)"
    r'(?:\?[^\s"]*)?\s+[^"]+"\s+'
    r"(?P<status>\d{3})"
)


class HealthCheckLogFilter(logging.Filter):
    """Suppress successful health-check access log lines.

    Docker's healthcheck hits /health every few seconds; logging each line
    buries everything else. Failures (status >= 400) still pass through so a
    flapping liveness check stays visible.
    """

    def __init__(self, paths: tuple[str, ...] = ("/health", "/healthz")) -> None:
        super().__init__()
        self.paths = paths

    def filter(self, record: logging.LogRecord) -> bool:
        match = _ACCESS_LOG_PATTERN.search(record.getMessage())
        if not match:
            return True
        if match.group("path") not in self.paths:
            return True
        try:
            status = int(match.group("status"))
        except ValueError:
            return True
        return status >= 400


logging.getLogger("granian.access").addFilter(HealthCheckLogFilter())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting MyGarage application...")

    # Log secret key status (key was generated during config import)
    if os.environ.get("MYGARAGE_SECRET_KEY"):
        logger.info("✓ Secret key loaded from MYGARAGE_SECRET_KEY environment variable")
    elif Path("/data/secret.key").exists():
        logger.info("✓ Secret key loaded from /data/secret.key")
    else:
        logger.warning("Secret key file not found - using temporary in-memory key")

    # Create data directories with error handling
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.attachments_dir.mkdir(parents=True, exist_ok=True)
        settings.photos_dir.mkdir(parents=True, exist_ok=True)
        settings.documents_dir.mkdir(parents=True, exist_ok=True)
        (settings.data_dir / "backups").mkdir(parents=True, exist_ok=True)
        logger.info("Data directories verified")
    except PermissionError as e:
        logger.warning("Could not create data directories (may already exist): %s", e)
        # Continue anyway - directories might already exist with correct permissions

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    # Initialize default settings
    from app.database import get_db_context
    from app.services.settings_init import initialize_default_settings

    async with get_db_context() as db:
        await initialize_default_settings(db)

        # Check for insecure auth_mode='none' and log warning
        from app.services.auth import get_auth_mode

        auth_mode = await get_auth_mode(db)
        if auth_mode == "none":
            logger.warning("=" * 80)
            logger.warning("⚠️  SECURITY WARNING: Authentication is disabled (auth_mode='none')")
            logger.warning("⚠️  All endpoints are accessible without authentication!")
            logger.warning("⚠️  This should NEVER be used in production environments!")
            logger.warning("=" * 80)

    # Start scheduled background tasks (session timeouts, device offline detection, etc.)
    from app.tasks.scheduled import start_scheduler, stop_scheduler

    start_scheduler()

    # Start MQTT subscriber if enabled
    from app.tasks.livelink_tasks import start_mqtt_subscriber, stop_mqtt_subscriber

    await start_mqtt_subscriber()

    yield

    # Stop MQTT subscriber on shutdown
    await stop_mqtt_subscriber()
    stop_scheduler()
    logger.info("Shutting down MyGarage application...")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Self-hosted vehicle maintenance tracking application",
    lifespan=lifespan,
    root_path=settings.root_path,
)

# Configure rate limiting
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# Add security middleware.
#
# Middleware order matters with pure ASGI middleware: the LAST `add_middleware`
# call is the OUTERMOST layer. CSRF short-circuits with a 403 by emitting
# the response directly, so layers added *after* it still see that response
# and can decorate it. We put CSRF innermost so its 403s flow back through
# RequestID (adds X-Request-ID) and SecurityHeaders (adds CSP, X-Frame-Options
# etc.) on the way out.
#
# NOTE: `SlowAPIMiddleware` deliberately omitted. As of slowapi 0.1.9 it is
# still a `BaseHTTPMiddleware` subclass, which buffers the response body
# through an asyncio queue and stalls streaming responses (proven on backup
# downloads: ~20 KB/s sustained with bursty 2s-on / 20s-off pattern). The
# middleware only enforces the global `default_limits` value — every
# rate-sensitive endpoint (auth, OIDC, exports, uploads, widget) already
# has an explicit `@limiter.limit(...)` decorator that does not depend on
# this middleware, and the Traefik `common-rates` chain provides the global
# floor (60 req/s per source IP).
from app.middleware import (
    CSRFProtectionMiddleware,
    IngestBodySizeLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)

# Innermost: the ingest body-size guard runs closest to the app, so its 413
# still flows out through RequestID + SecurityHeaders and is fully decorated.
app.add_middleware(IngestBodySizeLimitMiddleware)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Add error handlers
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.utils.error_handlers import (
    handle_database_error,
    handle_generic_exception,
    handle_validation_error,
)

if not settings.debug:
    # In production, use secure error handlers
    app.add_exception_handler(Exception, handle_generic_exception)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, handle_database_error)  # type: ignore[arg-type]

app.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,  # Required for cookie-based authentication
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-CSRF-Token",
    ],  # Added CSRF token header
    expose_headers=["Set-Cookie"],
    max_age=600,
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@app.get("/api/health")
async def api_health_check(request: Request):
    """API health check endpoint with authenticator detection."""
    # Check for reverse proxy authenticator headers
    auth_headers = [
        "x-forwarded-user",
        "remote-user",
        "x-auth-request-user",
        "x-authentik-username",
        "x-authentik-email",
        "x-authelia-user",
    ]

    authenticator_detected = any(
        header.lower() in [h.lower() for h in request.headers.keys()] for header in auth_headers
    )

    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "authenticator_detected": authenticator_detected,
    }


# Import and include routers
from app.routes import (
    address_book_router,
    analytics_router,
    attachments_router,
    backup_router,
    calendar_router,
    dashboard_router,
    def_router,
    documents_router,
    export_router,
    fuel_router,
    import_router,
    insurance_router,
    maintenance_templates_router,
    notes_router,
    notifications_router,
    odometer_router,
    photos_router,
    recalls_router,
    reminders_router,
    reports_router,
    service_visits_router,
    settings_router,
    shop_discovery_router,
    spot_rental_billing_router,
    spot_rental_router,
    tax_router,
    toll_tags_router,
    toll_transactions_router,
    vehicles_router,
    vendors_router,
    vin_router,
    warranty_router,
    window_sticker_router,
)
from app.routes.auth import router as auth_router
from app.routes.family import router as family_router
from app.routes.livelink import router as livelink_ingest_router
from app.routes.livelink_admin import router as livelink_admin_router
from app.routes.livelink_vehicle import router as livelink_vehicle_router
from app.routes.oidc import router as oidc_router
from app.routes.poi import router as poi_router
from app.routes.quick_entry import router as quick_entry_router
from app.routes.widget import router as widget_router
from app.routes.widget_keys import router as widget_keys_router
from app.routes.widget_v2 import router as widget_v2_router

app.include_router(auth_router)
app.include_router(family_router)
app.include_router(oidc_router)
app.include_router(vin_router)
app.include_router(vehicles_router)
app.include_router(photos_router)
app.include_router(fuel_router)
app.include_router(def_router)
app.include_router(odometer_router)
app.include_router(documents_router)
app.include_router(notes_router)
app.include_router(dashboard_router)
app.include_router(export_router)
app.include_router(import_router)
app.include_router(analytics_router)
app.include_router(warranty_router)
app.include_router(insurance_router)
app.include_router(reports_router)
app.include_router(toll_tags_router)
app.include_router(toll_transactions_router)
app.include_router(recalls_router)
app.include_router(settings_router)
app.include_router(backup_router)
app.include_router(attachments_router)
app.include_router(tax_router)
app.include_router(spot_rental_router)
app.include_router(spot_rental_billing_router)
app.include_router(address_book_router)
app.include_router(calendar_router)
app.include_router(window_sticker_router)
app.include_router(notifications_router)
app.include_router(maintenance_templates_router)
app.include_router(poi_router)  # New POI router
app.include_router(shop_discovery_router)  # Backward compatibility (deprecated)
app.include_router(vendors_router)
app.include_router(service_visits_router)
app.include_router(reminders_router)
app.include_router(livelink_ingest_router)
app.include_router(livelink_admin_router)
app.include_router(livelink_vehicle_router)
app.include_router(quick_entry_router)
app.include_router(widget_router)
app.include_router(widget_keys_router)
app.include_router(widget_v2_router)


# Serve static files (frontend build) in production
static_dir = Path(settings.static_dir)
if static_dir.exists():
    from fastapi.exception_handlers import http_exception_handler
    from fastapi.responses import FileResponse, HTMLResponse

    from app.utils.html_base import inject_base_href

    _index_shell = inject_base_href(
        (static_dir / "index.html").read_text(encoding="utf-8"), settings.root_path
    )

    # Mutable shell files (sw.js, manifest, index.html) must carry an explicit
    # no-cache: with no Cache-Control, Cloudflare edge-caches .js for 4h
    # (max-age=14400), so tunnel clients can run a stale service worker for
    # hours after a deploy. no-cache still allows ETag revalidation (304s).
    _NO_CACHE = {"Cache-Control": "no-cache"}

    # Serve PWA files with correct MIME types
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(
            static_dir / "sw.js", media_type="application/javascript", headers=_NO_CACHE
        )

    @app.get("/manifest.json", include_in_schema=False)
    async def manifest():
        return FileResponse(
            static_dir / "manifest.json", media_type="application/json", headers=_NO_CACHE
        )

    # Serve icon files with correct MIME type
    @app.get("/icon-192.png", include_in_schema=False)
    async def icon_192():
        return FileResponse(static_dir / "icon-192.png", media_type="image/png")

    @app.get("/icon-512.png", include_in_schema=False)
    async def icon_512():
        return FileResponse(static_dir / "icon-512.png", media_type="image/png")

    # Serve root index.html
    @app.get("/", include_in_schema=False)
    async def root():
        return HTMLResponse(_index_shell, headers=_NO_CACHE)

    # Mount static assets (CSS, JS, images) - must be after route definitions.
    #
    # Vite emits content-hashed filenames under /assets (e.g. main-abc123.js),
    # which are immutable for the life of the build. Telling browsers and CDNs
    # that with `immutable` + a year-long max-age stops them from re-fetching
    # or revalidating these on every navigation, which is where most of the
    # post-deploy reload latency comes from.
    class ImmutableStaticFiles(StaticFiles):
        async def get_response(self, path, scope):
            response = await super().get_response(path, scope)
            if response.status_code == 200:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    app.mount("/assets", ImmutableStaticFiles(directory=str(static_dir / "assets")), name="assets")

    # Mount translation files for non-English languages (loaded lazily by i18next)
    locales_dir = static_dir / "locales"
    if locales_dir.is_dir():
        app.mount("/locales", StaticFiles(directory=str(locales_dir)), name="locales")

    # Custom 404 handler to serve SPA for non-API routes
    @app.exception_handler(404)
    async def custom_404_handler(request: Request, exc: HTTPException):
        # If it's an API route, return the normal 404
        if request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)

        # Serve a genuine root-level static file (offline.html, favicon, etc.)
        # before falling back to the SPA shell. Path-traversal guarded.
        rel = request.url.path.lstrip("/")
        if rel:
            candidate = (static_dir / rel).resolve()
            if candidate.is_file() and static_dir.resolve() in candidate.parents:
                return FileResponse(candidate, headers=_NO_CACHE)

        # Otherwise serve the SPA
        return HTMLResponse(_index_shell, headers=_NO_CACHE)


if __name__ == "__main__":
    import subprocess
    import sys

    # Use same server as production (Granian) for consistency
    cmd = [
        "granian",
        "--interface",
        "asgi",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "app.main:app",
    ]

    # Enable auto-reload in debug mode
    if settings.debug:
        cmd.append("--reload")

    sys.exit(subprocess.run(cmd).returncode)
