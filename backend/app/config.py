"""Configuration settings for MyGarage application."""

import logging
import os
import re
import tomllib
from ipaddress import IPv4Network, IPv6Network, ip_network
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.utils.secret_key import get_or_create_secret_key


def get_version() -> str:
    """Read version from pyproject.toml (single source of truth)."""
    try:
        pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
        return data["project"]["version"]
    except FileNotFoundError, KeyError:
        # Fallback if pyproject.toml is not found or malformed
        return "0.0.0-dev"


# Default HTTP bind port. Single source of truth for both the field default and
# the service-link guard below (issue #102).
_DEFAULT_PORT = 8686

_IPV4_MAPPED = IPv6Network("::ffff:0:0/96")

# RFC 9110 token characters (\x60 is the backtick).
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_\x60|~0-9A-Za-z-]+")


def parse_trusted_proxies(raw: str) -> tuple[IPv4Network | IPv6Network, ...]:
    """Parse MYGARAGE_TRUSTED_PROXIES: comma-separated IPs or CIDRs.

    Host bits are masked, IPv4-mapped IPv6 entries become IPv4, and anything
    that would trust every client is refused with a ValueError.
    """
    networks: list[IPv4Network | IPv6Network] = []
    for part in raw.split(","):
        entry = part.strip()
        if not entry:
            continue
        everyone = (
            f"MYGARAGE_TRUSTED_PROXIES can't include {entry!r}: that trusts every client to "
            "pick its own address. List your proxy's IPs or networks instead."
        )
        if entry == "*":
            raise ValueError(everyone)
        try:
            net = ip_network(entry, strict=False)
        except ValueError:
            raise ValueError(
                f"MYGARAGE_TRUSTED_PROXIES has {entry!r}, which isn't an IP address or network "
                "(like 172.18.0.0/16)."
            ) from None
        # Mapped peers get turned into IPv4 before matching, so mapped entries have to as well.
        if isinstance(net, IPv6Network) and net.subnet_of(_IPV4_MAPPED):
            net = IPv4Network((int(net.network_address) & 0xFFFFFFFF, net.prefixlen - 96))
        # After the mapping on purpose: ::ffff:0:0/96 is 0.0.0.0/0 by now.
        if net.prefixlen == 0:
            raise ValueError(everyone)
        if isinstance(net, IPv6Network) and net.supernet_of(_IPV4_MAPPED):
            raise ValueError(
                f"MYGARAGE_TRUSTED_PROXIES has {entry!r}, which covers IPv4-mapped addresses. "
                "List the IPv4 networks instead."
            )
        networks.append(net)
    return tuple(networks)


def parse_client_ip_header(raw: str) -> str:
    """Parse MYGARAGE_CLIENT_IP_HEADER into a lowercase header name, or "" when unset.

    Refuses anything that isn't a valid header name, and X-Forwarded-For.
    """
    name = raw.strip()
    if not name:
        return ""
    if not _HEADER_NAME.fullmatch(name):
        raise ValueError(
            f"MYGARAGE_CLIENT_IP_HEADER {raw!r} isn't a valid header name "
            "(like CF-Connecting-IP or X-Real-IP)."
        )
    name = name.lower()
    if name == "x-forwarded-for":
        raise ValueError(
            "MYGARAGE_CLIENT_IP_HEADER can't be X-Forwarded-For, which is already read from "
            "trusted proxies. Leave it unset."
        )
    return name


class Settings(BaseSettings):
    """Application settings."""

    # Application
    app_name: str = "MyGarage"
    app_version: str = Field(default_factory=get_version)
    debug: bool = False
    # MYGARAGE_TIMEZONE: env fallback for the household zone when the Settings
    # row is absent. Read from os.environ by app/utils/household_time.py; this
    # field only documents the variable (the default is NOT a fallback value).
    timezone: str = "UTC"

    # Server
    host: str = "0.0.0.0"
    port: int = _DEFAULT_PORT

    @field_validator("port", mode="before")
    @classmethod
    def _ignore_service_link_port(cls, v: object) -> object:
        """Ignore Docker/Kubernetes service-link ``PORT`` variables.

        When a Kubernetes Service is named ``mygarage``, the kubelet injects a
        Docker-link compatibility variable ``MYGARAGE_PORT=tcp://<clusterIP>:<port>``.
        That collides exactly with ``env_prefix='MYGARAGE_'`` + this ``port``
        field, so pydantic tries to parse ``tcp://...`` as an int and crashes
        the app at startup (issue #102).

        Fall back to the default when the value is not a plain integer, so the
        app boots without requiring ``enableServiceLinks: false``. Explicit
        numeric overrides (e.g. ``MYGARAGE_PORT=9000``) are untouched.
        """
        if isinstance(v, str) and not v.strip().lstrip("+-").isdigit():
            logging.getLogger(__name__).warning(
                "Ignoring non-integer MYGARAGE_PORT=%r (looks like a "
                "Kubernetes/Docker service-link variable); falling back to "
                "default port %d. Set MYGARAGE_PORT to an integer, or set "
                "enableServiceLinks: false on the pod, to override.",
                v,
                _DEFAULT_PORT,
            )
            return _DEFAULT_PORT
        return v

    # Reverse-proxy subpath (issue #107). Empty = served at domain root. The
    # proxy must strip this prefix before forwarding; we use it to generate
    # correct doc/asset/media/OIDC URLs. Normalized to "/seg" or "".
    root_path: str = ""

    @field_validator("root_path", mode="before")
    @classmethod
    def _normalize_root_path(cls, v: object) -> str:
        """Normalize to '/seg[/seg...]' or ''. The value is interpolated into
        <base href> and generated URLs, so reject anything that isn't a plain
        path: query/fragment/backslash/quote/whitespace/dot-segments (Codex
        R1-F2). Operator-set, but validated as defense-in-depth."""
        if not v or not str(v).strip():
            return ""
        segments = [s for s in str(v).strip().strip("/").split("/") if s]
        if not segments:
            return ""
        seg_re = re.compile(r"^[A-Za-z0-9._~-]+$")
        for s in segments:
            if s in (".", "..") or not seg_re.match(s):
                raise ValueError(f"invalid MYGARAGE_ROOT_PATH segment: {s!r}")
        return "/" + "/".join(segments)

    # Who's allowed to tell us the client's address, and which header they put
    # it in. Empty trusts nobody, which is how it's always worked.
    trusted_proxies: Annotated[tuple[IPv4Network | IPv6Network, ...], NoDecode] = ()
    client_ip_header: str = ""

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def _parse_trusted_proxies(cls, v: object) -> object:
        """Parse the comma-separated env string; anything else passes through."""
        if isinstance(v, str):
            return parse_trusted_proxies(v)
        return v

    @field_validator("client_ip_header", mode="before")
    @classmethod
    def _parse_client_ip_header(cls, v: object) -> object:
        """Parse the env string; anything else passes through."""
        if isinstance(v, str):
            return parse_client_ip_header(v)
        return v

    # Database
    database_url: str = "sqlite+aiosqlite:////data/mygarage.db"

    # Maintenance mode. Starts the app far enough to apply migrations and no
    # further: no scheduler, no MQTT subscriber, and telemetry ingest answers
    # 503. It exists because the odometer repair tools must run before any new
    # reading lands, and migrations run inside this app's own lifespan, so
    # without it there is no window in which that instruction can be obeyed.
    maintenance_mode: bool = False

    # File Storage
    data_dir: Path = Path("/data")
    attachments_dir: Path = Path("/data/attachments")
    photos_dir: Path = Path("/data/photos")
    documents_dir: Path = Path("/data/documents")

    # Frontend build output served by the SPA-shell/static routes (issue #107).
    # Default unchanged from the previous hardcoded value so container
    # behavior is identical; overridable so the E2E harness can point at a
    # freshly built frontend/dist.
    static_dir: Path = Path("/app/static")

    # NHTSA API
    nhtsa_api_base_url: str = "https://vpic.nhtsa.dot.gov/api"

    # European VIN API (AutoRef / European VIN decoders)
    european_vin_api_base_url: str = "https://api.autoref.eu"
    european_vin_api_key: str = ""  # Empty by default (supports free tier or configured API key)

    # TomTom Places API (optional - falls back to OSM if not configured)
    tomtom_api_key: str = ""  # Empty by default - graceful degradation
    tomtom_api_base_url: str = "https://api.tomtom.com/search/2"
    shop_search_radius_meters: int = 8000  # ~5 miles
    shop_search_max_results: int = 20

    # Recall Checking
    recall_check_interval_days: int = 7

    # File Upload Limits
    max_upload_size_mb: int = 10
    max_document_size_mb: int = 25

    # Allowed file extensions
    allowed_photo_extensions: set[str] = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
    allowed_attachment_extensions: set[str] = {".jpg", ".jpeg", ".png", ".gif", ".pdf"}
    allowed_document_extensions: set[str] = {
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".txt",
        ".csv",
        ".jpg",
        ".jpeg",
        ".png",
    }

    # MIME types for validation
    allowed_attachment_mime_types: set[str] = {
        "image/jpeg",
        "image/png",
        "image/gif",
        "application/pdf",
    }

    # JWT Authentication
    secret_key: str = Field(default_factory=get_or_create_secret_key)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 120  # 2 hours

    # JWT Cookie Settings (Security Enhancement v2.10.0)
    jwt_cookie_name: str = "mygarage_token"
    jwt_cookie_httponly: bool = True
    jwt_cookie_samesite: str = "lax"  # Options: "lax", "strict", "none"

    @property
    def jwt_cookie_max_age(self) -> int:
        """Cookie max-age in seconds, derived from token expiry."""
        return self.access_token_expire_minutes * 60

    @property
    def jwt_cookie_secure(self) -> bool:
        """Auto-detect JWT cookie secure flag based on environment.

        Security defaults:
        - Production (debug=False): Secure=True (HTTPS only)
        - Development (debug=True): Secure=False (HTTP allowed)
        - Explicit override: Set JWT_COOKIE_SECURE env var

        This prevents session token exposure over unencrypted connections
        in production while allowing local development over HTTP.
        """
        env_value = os.getenv("JWT_COOKIE_SECURE", "auto").lower()

        if env_value in ("true", "1", "yes"):
            return True
        elif env_value in ("false", "0", "no"):
            return False
        else:  # auto mode
            # Secure by default in production, insecure in debug mode
            return not self.debug

    # Security Settings
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ]

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from environment or use defaults.

        Set MYGARAGE_CORS_ORIGINS as comma-separated URLs:
        MYGARAGE_CORS_ORIGINS=https://garage.example.com,https://app.example.com
        """
        env_origins = os.getenv("MYGARAGE_CORS_ORIGINS")
        if env_origins:
            return [origin.strip() for origin in env_origins.split(",")]
        return self.cors_origins  # Default localhost list

    rate_limit_default: str = "200/minute"
    rate_limit_uploads: str = "20/minute"
    rate_limit_auth: str = "5/minute"  # Strict limit for auth endpoints to prevent brute force
    rate_limit_exports: str = "5/minute"  # Strict limit for expensive export operations (PDF/CSV)
    rate_limit_webhooks: str = "60/minute"  # Shared-secret ingest, brute-force ceiling

    # CSV Import Settings
    max_csv_size_mb: int = 10

    @property
    def max_upload_size_bytes(self) -> int:
        """Convert max upload size to bytes."""
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_document_size_bytes(self) -> int:
        """Convert max document size to bytes."""
        return self.max_document_size_mb * 1024 * 1024

    @property
    def max_csv_size_bytes(self) -> int:
        """Convert max CSV size to bytes."""
        return self.max_csv_size_mb * 1024 * 1024

    model_config = SettingsConfigDict(env_prefix="MYGARAGE_")


settings = Settings()
