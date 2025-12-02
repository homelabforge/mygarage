# Multi-stage Dockerfile for MyGarage

# Stage 1: Build frontend
FROM node:24-alpine AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# Stage 2: Build backend
FROM python:3.14-slim AS backend-builder

WORKDIR /app

# Upgrade pip to latest version and clean up old metadata
RUN pip install --no-cache-dir --upgrade pip && \
    rm -rf /usr/local/lib/python3.14/site-packages/pip-25.2.dist-info 2>/dev/null || true

# Copy backend code and install with dependencies
COPY backend/ ./
RUN pip install --no-cache-dir .

# Stage 3: Production image
FROM python:3.14-slim

# Build arguments for metadata
ARG BUILD_DATE

# OCI-standard labels
LABEL org.opencontainers.image.authors="HomeLabForge"
LABEL org.opencontainers.image.title="MyGarage"
LABEL org.opencontainers.image.url="https://www.homelabforge.io"
LABEL org.opencontainers.image.description="Vehicle and garage management platform with maintenance tracking"

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
