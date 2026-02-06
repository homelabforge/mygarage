# ==============================================================================
# Multi-stage Dockerfile for MyGarage
# Frontend: Bun 1.3.8
# Backend: Python 3.14-slim
# ==============================================================================

# Stage 1: Build frontend with Bun
FROM oven/bun:1.3.8-alpine AS frontend-builder

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

WORKDIR /app

# Prevent bytecode during build (speeds up and reduces image size)
ENV PYTHONDONTWRITEBYTECODE=1

# Upgrade pip to latest version and clean up old metadata
RUN pip install --no-cache-dir --upgrade pip==26.0.1 && \
    rm -rf /usr/local/lib/python3.14/site-packages/pip-25.3.dist-info 2>/dev/null || true

# Copy backend code and install with dependencies (production only)
COPY backend/ ./
RUN pip install --no-cache-dir "."

# Stage 3: Production image
FROM python:3.14-slim

# Build arguments for metadata
ARG BUILD_DATE

# OCI-standard labels
LABEL org.opencontainers.image.authors="HomeLabForge"
LABEL org.opencontainers.image.title="MyGarage"
LABEL org.opencontainers.image.url="https://www.homelabforge.io"
LABEL org.opencontainers.image.description="Vehicle and garage management platform with maintenance tracking"
LABEL org.opencontainers.image.frontend.builder="bun-1.3.8"

# HTTP server metadata
LABEL http.server.name="granian"
LABEL http.server.version="2.7.0"
LABEL http.server.type="asgi"

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        libmagic1t64 \
        file && \
    rm -rf /var/lib/apt/lists/*

# Copy Python dependencies from builder
COPY --from=backend-builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Copy backend application code
COPY --from=backend-builder /app/app ./app
COPY --from=backend-builder /app/pyproject.toml ./pyproject.toml

# Copy frontend build
COPY --from=frontend-builder /app/frontend/dist ./static

# Create non-root user for security
RUN useradd --uid 1000 --user-group --system --create-home --no-log-init mygarage

# Create data directory and set proper permissions
RUN mkdir -p /data /data/attachments /data/photos && \
    chown -R mygarage:mygarage /app /data && \
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
