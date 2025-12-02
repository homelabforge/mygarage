"""Configuration settings for MyGarage application."""

import os
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from app.utils.secret_key import get_or_create_secret_key


class Settings(BaseSettings):
    """Application settings."""

    # Application
    app_name: str = "MyGarage"
    app_version: str = "2.14.0"
    debug: bool = False
    timezone: str = "UTC"  # User-editable via Settings UI

    # Server
    host: str = "0.0.0.0"
    port: int = 8686

    # Database
    database_url: str = "sqlite+aiosqlite:////data/mygarage.db"

    # File Storage
    data_dir: Path = Path("/data")
    attachments_dir: Path = Path("/data/attachments")
    photos_dir: Path = Path("/data/photos")
    documents_dir: Path = Path("/data/documents")

    # NHTSA API
    nhtsa_api_base_url: str = "https://vpic.nhtsa.dot.gov/api"

    # Recall Checking
    recall_check_interval_days: int = 7

    # File Upload Limits
    max_upload_size_mb: int = 10
    max_document_size_mb: int = 25

    # Allowed file extensions
    allowed_photo_extensions: set = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
    allowed_attachment_extensions: set = {".jpg", ".jpeg", ".png", ".gif", ".pdf"}
    allowed_document_extensions: set = {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx",
        ".txt", ".csv", ".jpg", ".jpeg", ".png"
    }

    # MIME types for validation
    allowed_attachment_mime_types: set = {
        "image/jpeg", "image/png", "image/gif",
        "application/pdf"
    }

    # JWT Authentication
    secret_key: str = Field(default_factory=get_or_create_secret_key)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours

    # JWT Cookie Settings (Security Enhancement v2.10.0)
    jwt_cookie_name: str = "mygarage_token"
    jwt_cookie_httponly: bool = True
    jwt_cookie_samesite: str = "lax"  # Options: "lax", "strict", "none"
    jwt_cookie_max_age: int = 60 * 24 * 60  # 24 hours in seconds

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
    auth_enabled: bool = True
    allow_auth_none: bool = False  # Allow auth_mode='none' in production (security risk!)
    cors_origins: list = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8000",
    ]

    @property
    def cors_origins_list(self) -> list:
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

    class Config:
        env_prefix = "MYGARAGE_"
        # No env_file required - all settings have sensible defaults


settings = Settings()
