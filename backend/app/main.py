"""Main FastAPI application for MyGarage."""

import logging
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

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Filter to exclude health check endpoints from access logs
class EndpointFilter(logging.Filter):
    """Filter to exclude specific endpoints from Granian access logs."""

    def __init__(self, excluded_paths: list[str]) -> None:
        super().__init__()
        self.excluded_paths = excluded_paths

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False if the log record is for an excluded endpoint."""
        # Granian access logs have the path in the message
        message = record.getMessage()
        return not any(path in message for path in self.excluded_paths)


# Apply filter to granian access logger to exclude health checks
logging.getLogger("granian.access").addFilter(EndpointFilter(["/health"]))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting MyGarage application...")

    # Log secret key status (key was generated during config import)
    secret_key_file = Path("/data/secret.key")
    if secret_key_file.exists():
        logger.info("✓ Secret key loaded from %s", secret_key_file)
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
            logger.warning(
                "⚠️  SECURITY WARNING: Authentication is disabled (auth_mode='none')"
            )
            logger.warning("⚠️  All endpoints are accessible without authentication!")
            logger.warning("⚠️  This should NEVER be used in production environments!")
            logger.warning("=" * 80)

    yield

    logger.info("Shutting down MyGarage application...")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Self-hosted vehicle maintenance tracking application",
    lifespan=lifespan,
)

# Configure rate limiting
limiter = Limiter(
    key_func=get_remote_address, default_limits=[settings.rate_limit_default]
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# Add security middleware
from slowapi.middleware import SlowAPIMiddleware

from app.middleware import (
    CSRFProtectionMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(CSRFProtectionMiddleware)
app.add_middleware(SlowAPIMiddleware)

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
    allow_origins=settings.cors_origins,
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
        header.lower() in [h.lower() for h in request.headers.keys()]
        for header in auth_headers
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
    documents_router,
    export_router,
    fuel_router,
    import_router,
    insurance_router,
    maintenance_schedule_router,
    maintenance_templates_router,
    notes_router,
    notifications_router,
    odometer_router,
    photos_router,
    recalls_router,
    reminders_router,
    reports_router,
    service_router,
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
from app.routes.oidc import router as oidc_router
from app.routes.poi import router as poi_router

app.include_router(auth_router)
app.include_router(oidc_router)
app.include_router(vin_router)
app.include_router(vehicles_router)
app.include_router(photos_router)
app.include_router(service_router)
app.include_router(fuel_router)
app.include_router(odometer_router)
app.include_router(documents_router)
app.include_router(reminders_router)
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
app.include_router(maintenance_schedule_router)


# Serve static files (frontend build) in production
static_dir = Path("/app/static")
if static_dir.exists():
    from fastapi.exception_handlers import http_exception_handler
    from fastapi.responses import FileResponse

    # Serve PWA files with correct MIME types
    @app.get("/sw.js", include_in_schema=False)
    async def service_worker():
        return FileResponse(static_dir / "sw.js", media_type="application/javascript")

    @app.get("/manifest.json", include_in_schema=False)
    async def manifest():
        return FileResponse(static_dir / "manifest.json", media_type="application/json")

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
        return FileResponse(static_dir / "index.html", media_type="text/html")

    # Mount static assets (CSS, JS, images) - must be after route definitions
    app.mount(
        "/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets"
    )

    # Custom 404 handler to serve SPA for non-API routes
    @app.exception_handler(404)
    async def custom_404_handler(request: Request, exc: HTTPException):
        # If it's an API route, return the normal 404
        if request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)

        # Otherwise serve the SPA
        return FileResponse(static_dir / "index.html")


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
