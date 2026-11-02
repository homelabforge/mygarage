# ==============================================================================
# Multi-stage Dockerfile for MyGarage
# Frontend: Bun (version pinned by .bun-version, passed as BUN_VERSION build-arg)
# Backend: Python 3.14-slim
# ==============================================================================

ARG BUN_VERSION=1.4.4

# Stage 1: Build frontend with Bun
#
# glibc, NOT alpine. Vite 8 bundles with Rolldown (native Rust); its chunk
# render phase is allocation-heavy across every core, and musl's globally
# locked malloc serialises it. Measured on this tree, same bun 1.3.14 and
# the same lockfile: alpine ~1090s, slim 0.38s. The musl binding loads fine
# — it is the allocator, not a missing/WASM fallback, so pinning a binding
# would not help. Build-stage only: just dist/ is copied into the
# python:3.14-slim runtime, so this costs the shipped image nothing.
FROM oven/bun:${BUN_VERSION}-slim AS frontend-builder

# Set working directory
WORKDIR /app/frontend

# Copy package files (Bun uses bun.lock instead of package-lock.json)
COPY frontend/package.json frontend/bun.lock ./

# Install dependencies
# --frozen-lockfile: Ensures reproducible builds (like npm ci)
RUN bun install --frozen-lockfile

# Copy frontend source
COPY frontend/ ./

# Build production bundle
# Bun runs Vite, which produces identical output to Node.js version
RUN bun run build

# Verify build output exists (fail fast if build failed)
RUN test -d dist && test -f dist/index.html

# Stage 2: Build backend
FROM python:3.14-slim AS backend-builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Prevent bytecode during build (speeds up and reduces image size)
ENV PYTHONDONTWRITEBYTECODE=1

# Install dependencies from the LOCKFILE, not pyproject.toml. Every constraint
# in pyproject.toml is a bare `>=` floor, so installing from it resolved fresh
# on every build: two builds of the same commit on different days produced
# different dependency sets, and the versions the test image pinned via
# `uv sync --frozen` were never the versions production ran. Exporting the lock
# to a hash-pinned requirements file keeps `--system` installs while making the
# build reproducible and hash-verified.
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --frozen --no-dev --no-emit-project --format requirements-txt \
      -o /tmp/requirements.txt \
    && uv pip install --system --no-cache --require-hashes -r /tmp/requirements.txt

# Copy backend code and install the project itself
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache --no-deps .

# Stage 3: Production image
FROM python:3.14-slim

# Build arguments for metadata
ARG BUILD_DATE
# Re-declare BUN_VERSION inside this stage — Docker ARG scope resets at every
# FROM. Without this redeclaration, ${BUN_VERSION} expands to empty in LABEL.
ARG BUN_VERSION

# OCI-standard labels
LABEL org.opencontainers.image.authors="HomeLabForge"
LABEL org.opencontainers.image.title="MyGarage"
LABEL org.opencontainers.image.url="https://www.homelabforge.io"
LABEL org.opencontainers.image.description="Vehicle and garage management platform with maintenance tracking"
LABEL org.opencontainers.image.frontend.builder="bun-${BUN_VERSION}"

WORKDIR /app

# Install runtime dependencies, create non-root user, and set up directories.
# tesseract-ocr is the engine pytesseract drives: it reads photos and scanned
# PDFs (insurance import, window stickers, receipt photos). English only.
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        curl \
        libmagic1t64 \
        file \
        postgresql-client \
        tesseract-ocr \
        tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/* && \
    useradd --uid 1000 --user-group --system --create-home --no-log-init mygarage && \
    mkdir -p /data /data/attachments /data/photos

# Tesseract's OpenMP would otherwise start a thread per core for every OCR
# call, and the OCR calls already run several at once in the thread pool.
ENV OMP_THREAD_LIMIT=1

# Copy Python dependencies from builder
COPY --from=backend-builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy backend application code
COPY --from=backend-builder /app/app ./app
COPY --from=backend-builder /app/pyproject.toml ./pyproject.toml

# The household timezone feature resolves IANA zones at runtime; a slim image
# has no system tzdata, so this asserts the copied packages carry it.
RUN python -c "from zoneinfo import ZoneInfo; ZoneInfo('America/Chicago')" 

# SQLAlchemy 2.1 only brings greenlet with its [asyncio] extra, and without it the
# app dies on import. Docker Build Test never starts the app, so run a real query
# through the async engine here, and load the asyncpg and psycopg2 drivers too.
RUN python - <<'EOF'
import asyncio

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.connect() as conn:
        assert (await conn.execute(text("select 1"))).scalar_one() == 1
    await engine.dispose()


asyncio.run(main())
create_async_engine("postgresql+asyncpg://smoke@localhost/smoke")
create_engine("postgresql+psycopg2://smoke@localhost/smoke")
EOF

# pytesseract is only a wrapper around the tesseract binary, and the OCR
# services swallow a missing binary and return "", so an image without it
# builds, starts and passes health checks while every photo and scanned PDF
# reads as blank. Read a rendered word back through the service, once from a
# PNG and once from an image-only PDF, so a missing engine fails the build.
# No bytecode: the imports here would otherwise leave about 25 MB of .pyc.
RUN PYTHONDONTWRITEBYTECODE=1 python - <<'EOF'
import asyncio
import io

import fitz
from PIL import Image, ImageDraw, ImageFont

from app.services.document_ocr import DocumentOCRService

image = Image.new("L", (900, 200), 255)
font = ImageFont.load_default(size=72)
ImageDraw.Draw(image).text((40, 50), "GARAGE 4815", fill=0, font=font)
png = io.BytesIO()
image.save(png, format="PNG")

with fitz.open() as doc:
    page = doc.new_page()
    page.insert_image(page.rect, stream=png.getvalue())
    pdf = doc.tobytes()

service = DocumentOCRService()
assert service.get_ocr_status()["tesseract_available"], "tesseract not found"
for label, data, is_pdf in (("PNG", png.getvalue(), False), ("scanned PDF", pdf, True)):
    text = asyncio.run(service.extract_text_from_bytes(data, is_pdf=is_pdf))
    assert "4815" in text, f"OCR read nothing usable from a {label}: {text!r}"
EOF

# Copy the maintenance tools. The upgrade notes in CHANGELOG.md tell operators
# to run these against a live instance, and without this they are not in the
# image at all: every documented command failed with "can't open file".
# They import `app.*` and expect to run from this directory.
COPY --from=backend-builder /app/tools ./tools

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist ./static

# Set ownership and permissions
RUN chown -R mygarage:mygarage /app /data && \
    chmod -R 755 /app && \
    chmod -R 755 /data

# Switch to non-root user
USER mygarage

# Expose port
EXPOSE 8686

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8686/health || exit 1

# Run application with Granian (Rust-based ASGI server)
# Using --workers 1 due to APScheduler requiring single-process mode
CMD ["granian", "--interface", "asgi", "--host", "0.0.0.0", "--port", "8686", "--workers", "1", "app.main:app"]
