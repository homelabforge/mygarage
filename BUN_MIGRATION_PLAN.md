# MyGarage Bun Migration Plan

**Version:** 1.0
**Target Bun Version:** 1.3.4
**Date Created:** 2024-12-08
**Estimated Effort:** 4-6 hours (initial migration + testing)
**Risk Level:** LOW

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Migration Philosophy](#migration-philosophy)
3. [Current vs Target Architecture](#current-vs-target-architecture)
4. [Detailed Migration Steps](#detailed-migration-steps)
5. [Development Workflow Changes](#development-workflow-changes)
6. [Testing Strategy](#testing-strategy)
7. [Docker Configuration](#docker-configuration)
8. [CI/CD Pipeline Updates](#cicd-pipeline-updates)
9. [Rollback Plan](#rollback-plan)
10. [Performance Benchmarks](#performance-benchmarks)
11. [Troubleshooting Guide](#troubleshooting-guide)
12. [Post-Migration Checklist](#post-migration-checklist)

---

## Executive Summary

### What We're Doing
Migrating MyGarage's frontend build toolchain from Node.js 25 to Bun 1.3.4, leveraging Bun's built-in features to replace third-party tools where Bun's implementation is superior or equivalent.

### Why We're Doing It
- **Performance:** 10-25x faster package installation, 2-5x faster dev server startup
- **Simplicity:** Single runtime with built-in TypeScript, JSX, and bundling
- **Developer Experience:** Faster iteration cycles, instant feedback
- **Production Benefits:** Smaller Docker images (~40-60% reduction), faster CI/CD

### What Won't Change
- **Backend:** Stays on Python 3.14 + FastAPI + Granian
- **Application Code:** Zero changes to React components, hooks, services
- **APIs:** No changes to endpoints or authentication
- **Database:** SQLite remains unchanged

### Migration Approach
**Incremental, Conservative, Reversible**
- Phase 1: Replace Node.js runtime with Bun, keep Vite
- Phase 2: Evaluate Bun native features (optional optimizations)
- Phase 3: Monitor and optimize based on real-world performance

---

## Migration Philosophy

### Built-in vs Third-Party Decision Matrix

| Feature | Current (Third-Party) | Bun Built-in | Decision | Rationale |
|---------|----------------------|--------------|----------|-----------|
| **Runtime** | Node.js 25 | Bun 1.3.4 | ✅ **Use Bun** | Core migration goal |
| **Package Manager** | npm | `bun install` | ✅ **Use Bun** | 10-25x faster, native lockfile |
| **TypeScript Transpilation** | @vitejs/plugin-react-swc | Bun native | ⏸️ **Keep SWC (Phase 1)** | Proven, works well. Evaluate in Phase 2 |
| **Bundler** | Vite + Rollup | Bun.build() | ⏸️ **Keep Vite (Phase 1)** | Vite is mature, well-configured. Migrate in Phase 2 if needed |
| **Dev Server** | Vite dev server | Bun.serve() | ⏸️ **Keep Vite (Phase 1)** | Vite HMR is battle-tested |
| **Test Runner** | Vitest | bun:test | ⏸️ **Keep Vitest (Phase 1)** | Existing test suite, mature tooling |
| **Test Environment** | jsdom (via Vitest) | happy-dom (Bun native) | ⏸️ **Keep jsdom (Phase 1)** | Proven compatibility |
| **Linter** | ESLint 9 | N/A | ✅ **Keep ESLint** | No Bun alternative |
| **CSS Framework** | Tailwind CSS 4 | N/A | ✅ **Keep Tailwind** | No Bun alternative |

### Guiding Principles

1. **Pragmatic over Purist**
   - Use Bun built-ins when they're better or equal
   - Keep third-party when they're superior or migration is risky

2. **Incremental Migration**
   - Phase 1: Minimal changes (runtime swap only)
   - Phase 2: Optimize with Bun features (optional)
   - Phase 3: Long-term refinement

3. **Reversibility First**
   - Every step must be easily reversible
   - Keep Node.js Dockerfile commented out as backup
   - Git tags for each migration phase

4. **Production Stability**
   - No "big bang" deployments
   - Test thoroughly in dev environment first
   - Parallel testing (Node.js vs Bun builds)

---

## Current vs Target Architecture

### Current Architecture (Node.js 25)

```
┌─────────────────────────────────────────────────────────────┐
│                     DEVELOPMENT                              │
├─────────────────────────────────────────────────────────────┤
│  Terminal 1: Backend (Python)                               │
│    python -m granian app.main:app --port 8686              │
│                                                             │
│  Terminal 2: Frontend (Node.js)                             │
│    npm ci              ← Node.js package manager            │
│    npm run dev         ← Node.js runs Vite dev server       │
│      ├── Vite (bundler)                                     │
│      ├── @vitejs/plugin-react-swc (transpiler)             │
│      ├── @tailwindcss/vite (CSS processor)                 │
│      └── HMR on localhost:3000                              │
│                                                             │
│  Browser: localhost:3000 → proxies /api to :8686           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     PRODUCTION BUILD                         │
├─────────────────────────────────────────────────────────────┤
│  Dockerfile - Stage 1: Frontend Builder                     │
│    FROM node:25-alpine                                       │
│    RUN npm ci                                                │
│    RUN npm run build → /dist (static files)                 │
│                                                             │
│  Dockerfile - Stage 2: Backend Builder                      │
│    FROM python:3.14-slim                                     │
│    RUN pip install .[dev]                                   │
│                                                             │
│  Dockerfile - Stage 3: Production Runtime                   │
│    FROM python:3.14-slim                                     │
│    COPY --from=frontend-builder /app/frontend/dist /static │
│    COPY --from=backend-builder /usr/local/lib/python3.14   │
│    CMD granian --port 8686 app.main:app                     │
│                                                             │
│  Result: Single container (512M limit)                      │
│    - Granian serves /static/* (React SPA)                   │
│    - Granian serves /api/* (FastAPI)                        │
│    - Port 12347:8686                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     CI/CD (GitHub Actions)                   │
├─────────────────────────────────────────────────────────────┤
│  test-frontend:                                             │
│    - setup-node@v4 (Node.js 25)                             │
│    - npm ci                                                  │
│    - npx tsc --noEmit (type checking)                       │
│    - npm run lint                                            │
│    - npm test -- --run (Vitest)                             │
│                                                             │
│  docker-build-test:                                         │
│    - docker build (uses Node.js 25 stage)                   │
└─────────────────────────────────────────────────────────────┘
```

### Target Architecture (Bun 1.3.4 - Phase 1)

```
┌─────────────────────────────────────────────────────────────┐
│                     DEVELOPMENT                              │
├─────────────────────────────────────────────────────────────┤
│  Terminal 1: Backend (Python) - UNCHANGED                   │
│    python -m granian app.main:app --port 8686              │
│                                                             │
│  Terminal 2: Frontend (Bun)                                 │
│    bun install         ← Bun package manager (10-25x faster)│
│    bun dev             ← Bun runs Vite dev server           │
│      ├── Vite (bundler) - SAME                              │
│      ├── @vitejs/plugin-react-swc - SAME                    │
│      ├── @tailwindcss/vite - SAME                           │
│      └── HMR on localhost:3000 - SAME                       │
│                                                             │
│  Browser: localhost:3000 → proxies /api to :8686 - SAME    │
│                                                             │
│  CHANGES:                                                   │
│    ✓ Runtime: Node.js → Bun (faster startup)                │
│    ✓ Package manager: npm → bun (faster installs)          │
│    ✗ Everything else: IDENTICAL                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     PRODUCTION BUILD                         │
├─────────────────────────────────────────────────────────────┤
│  Dockerfile - Stage 1: Frontend Builder                     │
│    FROM oven/bun:1.3.4-alpine         ← CHANGED             │
│    RUN bun install --frozen-lockfile  ← CHANGED             │
│    RUN bun run build → /dist          ← CHANGED             │
│                                                             │
│  Dockerfile - Stage 2: Backend Builder - UNCHANGED         │
│    FROM python:3.14-slim                                     │
│    RUN pip install .[dev]                                   │
│                                                             │
│  Dockerfile - Stage 3: Production Runtime - UNCHANGED      │
│    FROM python:3.14-slim                                     │
│    COPY --from=frontend-builder /build/dist /static        │
│    COPY --from=backend-builder /usr/local/lib/python3.14   │
│    CMD granian --port 8686 app.main:app                     │
│                                                             │
│  Result: Same container, smaller image (~40-60% reduction) │
│    - Base image: ~90MB (Bun) vs ~180MB (Node Alpine)       │
│    - Faster build times (parallel installs + caching)       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     CI/CD (GitHub Actions)                   │
├─────────────────────────────────────────────────────────────┤
│  test-frontend:                                             │
│    - oven-sh/setup-bun@v2 (Bun 1.3.4)    ← CHANGED         │
│    - bun install --frozen-lockfile       ← CHANGED         │
│    - bun run type-check (or bunx tsc)    ← CHANGED         │
│    - bun run lint                         ← CHANGED         │
│    - bun test                             ← CHANGED         │
│                                                             │
│  docker-build-test: - UNCHANGED (uses Dockerfile)          │
│    - docker build (now uses Bun 1.3.4 stage)               │
└─────────────────────────────────────────────────────────────┘
```

### Target Architecture (Bun 1.3.4 - Phase 2, Optional)

**After Phase 1 proves stable, optionally evaluate:**

```
┌─────────────────────────────────────────────────────────────┐
│               PHASE 2: NATIVE BUN FEATURES (OPTIONAL)        │
├─────────────────────────────────────────────────────────────┤
│  Option A: Replace Vite with Bun.build()                    │
│    - Simpler config (bunfig.toml vs vite.config.ts)        │
│    - Faster builds (native bundler)                         │
│    - Manual HMR implementation required                     │
│    - EFFORT: Medium (4-6 hours to rewrite config)           │
│                                                             │
│  Option B: Replace Vitest with bun:test                     │
│    - Faster test execution (~2-3x)                          │
│    - Simpler setup (no jsdom config needed)                 │
│    - Different API (test migration needed)                  │
│    - EFFORT: Medium-High (rewrite all test files)           │
│                                                             │
│  Option C: Use Bun's native transpiler                      │
│    - Remove @vitejs/plugin-react-swc dependency             │
│    - Bun handles JSX/TSX natively                           │
│    - Requires Vite config changes                           │
│    - EFFORT: Low (1-2 hours)                                │
│                                                             │
│  RECOMMENDATION: Evaluate after 2-4 weeks of Phase 1        │
│    - Measure actual performance gains                       │
│    - Consider maintenance burden vs benefits                │
│    - Only migrate if clear advantages                       │
└─────────────────────────────────────────────────────────────┘
```

---

## Detailed Migration Steps

### Pre-Migration Preparation

#### Step 0.1: Backup Current State
```bash
# Create backup branch
cd /srv/raid0/docker/build/mygarage
git checkout -b backup/pre-bun-migration
git add -A
git commit -m "backup: Pre-Bun migration state (Node.js 25)"
git tag backup-node25-$(date +%Y%m%d)

# Return to main development branch
git checkout main
git checkout -b feature/bun-migration

# Document current versions
cat > MIGRATION_BASELINE.md << 'EOF'
# Pre-Migration Baseline (Node.js 25)

## Package Versions
- Node.js: 25-alpine
- npm: (check with `npm --version`)
- Vite: 7.2.4
- React: 19.2.0
- TypeScript: 5.9.3

## Build Times (measure these)
- npm ci: _____ seconds
- npm run build: _____ seconds
- npm run dev (startup): _____ seconds
- npm test: _____ seconds

## Docker Image Sizes
- Frontend builder stage: _____ MB
- Final production image: _____ MB

## Test Results
- Unit tests: _____ passed / _____ total
- Coverage: _____%
- Type errors: 0
- Lint errors: 0

Date: $(date)
EOF

# Measure baseline performance
echo "Measuring baseline..."
time npm ci
time npm run build
# Record these times in MIGRATION_BASELINE.md
```

#### Step 0.2: Install Bun Locally (Dev Machine)
```bash
# Install Bun 1.3.4 on your development machine
curl -fsSL https://bun.sh/install | bash

# Verify installation
bun --version  # Should show 1.3.4 or 1.3.x

# Optional: Install specific version
# curl -fsSL https://bun.sh/install | bash -s "bun-v1.3.4"
```

#### Step 0.3: Audit Current Dependencies
```bash
cd /srv/raid0/docker/build/mygarage/frontend

# Check for Node.js-specific dependencies
grep -i "node" package.json

# Check for native modules
npm ls | grep -E "\.(node|gyp)"

# Document findings
# (Expected: Only build-time native modules, all compatible with Bun)
```

---

### Phase 1: Core Migration (Bun Runtime with Vite)

**Goal:** Replace Node.js with Bun while keeping all existing tools (Vite, Vitest, etc.)
**Time Estimate:** 2-3 hours
**Risk:** LOW

#### Step 1.1: Update Frontend package.json

**File:** `frontend/package.json`

**Changes:**
1. Add `"bun"` field to specify Bun version
2. Optionally add Bun-specific scripts

```bash
cd /srv/raid0/docker/build/mygarage/frontend
```

**Edit [frontend/package.json](frontend/package.json):**

```json
{
  "name": "mygarage-frontend",
  "private": true,
  "version": "2.14.2",
  "type": "module",
  "bun": "^1.3.4",  // ← ADD: Specify Bun version
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "lint": "eslint . --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "preview": "vite preview",
    "test": "vitest",
    "test:ui": "vitest --ui",
    "test:coverage": "vitest --coverage",
    "test:run": "vitest run",
    // ← ADD: Type checking script for CI
    "type-check": "tsc --noEmit"
  },
  // ... rest unchanged
}
```

**No other changes needed** - all dependencies remain the same.

#### Step 1.2: Create Bun Lockfile

```bash
cd /srv/raid0/docker/build/mygarage/frontend

# Remove Node.js artifacts
rm -rf node_modules package-lock.json

# Install with Bun (creates bun.lockb)
bun install

# Verify installation
ls -lh node_modules | head
bun pm ls  # List installed packages

# Test that everything still works
bun run dev  # Start dev server, test in browser
# CTRL+C to stop

bun run build  # Test production build
bun test  # Run test suite
bun run lint  # Run linter
```

**Expected Results:**
- ✅ `bun.lockb` created (binary lockfile)
- ✅ `node_modules` populated (faster than npm ci)
- ✅ All scripts work identically
- ✅ Tests pass
- ✅ Build completes successfully

**Git Checkpoint:**
```bash
git add frontend/package.json frontend/bun.lockb
git rm frontend/package-lock.json
git commit -m "chore(frontend): migrate to Bun 1.3.4 package manager

- Add bun field to package.json
- Replace package-lock.json with bun.lockb
- Verified: build, test, lint all pass
"
```

#### Step 1.3: Update Dockerfile for Bun

**File:** [Dockerfile](Dockerfile)

**Strategy:**
1. Replace Node.js builder stage with Bun
2. Keep backend stages identical
3. Add comments for easy rollback

```dockerfile
# ==============================================================================
# Multi-stage Dockerfile for MyGarage
# Frontend: Bun 1.3.4 (migrated from Node.js 25)
# Backend: Python 3.14
# ==============================================================================

# Stage 1: Build frontend with Bun
FROM oven/bun:1.3.4-alpine AS frontend-builder

# Set working directory
WORKDIR /app/frontend

# Copy package files (Bun uses bun.lockb instead of package-lock.json)
COPY frontend/package.json frontend/bun.lockb ./

# Install dependencies
# --frozen-lockfile: Ensures reproducible builds (like npm ci)
# --production: Would skip devDependencies, but we need them for build
RUN bun install --frozen-lockfile

# Copy frontend source
COPY frontend/ ./

# Build production bundle
# Bun runs Vite, which produces identical output to Node.js version
RUN bun run build

# Verify build output exists (fail fast if build failed)
RUN test -d dist && test -f dist/index.html

# ==============================================================================
# ROLLBACK OPTION: Uncomment below to revert to Node.js 25
# ==============================================================================
# FROM node:25-alpine AS frontend-builder
# WORKDIR /app/frontend
# COPY frontend/package*.json ./
# RUN npm ci
# COPY frontend/ ./
# RUN npm run build
# ==============================================================================

# Stage 2: Build backend (UNCHANGED)
FROM python:3.14-slim AS backend-builder

WORKDIR /app

# Upgrade pip to latest version and clean up old metadata
RUN pip install --no-cache-dir --upgrade pip && \
    rm -rf /usr/local/lib/python3.14/site-packages/pip-25.2.dist-info 2>/dev/null || true

# Copy backend code and install with dependencies (including dev/test dependencies)
COPY backend/ ./
RUN pip install --no-cache-dir ".[dev]"

# Stage 3: Production image (UNCHANGED)
FROM python:3.14-slim

# Build arguments for metadata
ARG BUILD_DATE

# OCI-standard labels
LABEL org.opencontainers.image.authors="HomeLabForge"
LABEL org.opencontainers.image.title="MyGarage"
LABEL org.opencontainers.image.url="https://www.homelabforge.io"
LABEL org.opencontainers.image.description="Vehicle and garage management platform with maintenance tracking"
LABEL org.opencontainers.image.frontend.builder="bun-1.3.4"

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

# Copy backend application code and tests
COPY --from=backend-builder /app/app ./app
COPY --from=backend-builder /app/tests ./tests
COPY --from=backend-builder /app/pytest.ini ./pytest.ini
COPY --from=backend-builder /app/pyproject.toml ./pyproject.toml

# Copy frontend build (from Bun builder)
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
```

**Key Changes:**
- Line 7: `FROM oven/bun:1.3.4-alpine` (was `node:25-alpine`)
- Line 13: Copy `bun.lockb` instead of `package-lock.json`
- Line 17: `bun install --frozen-lockfile` (was `npm ci`)
- Line 23: `bun run build` (was `npm run build`)
- Line 26: Added build verification
- Line 30-36: Rollback instructions (commented)
- Line 74: Added label for tracking

**Git Checkpoint:**
```bash
git add Dockerfile
git commit -m "build(docker): migrate frontend builder to Bun 1.3.4

- Replace node:25-alpine with oven/bun:1.3.4-alpine
- Update install command: npm ci → bun install --frozen-lockfile
- Update build command: npm run build → bun run build
- Add build verification step
- Add rollback comments for easy revert
- Backend stages remain unchanged
"
```

#### Step 1.4: Test Docker Build Locally

```bash
cd /srv/raid0/docker/build/mygarage

# Build with Bun
time docker build -t mygarage:bun-test .

# Expected output:
# [frontend-builder 3/6] RUN bun install --frozen-lockfile
# (Should be faster than npm ci)
# [frontend-builder 5/6] RUN bun run build
# (Should complete successfully)

# Verify build succeeded
docker images | grep mygarage

# Compare image sizes
docker images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}" | grep mygarage

# Test run container
docker run -d \
  --name mygarage-bun-test \
  -p 12348:8686 \
  -v $(pwd)/data:/data \
  -e DEBUG=true \
  -e JWT_COOKIE_SECURE=false \
  mygarage:bun-test

# Wait for startup
sleep 10

# Test health endpoint
curl http://localhost:12348/health
# Expected: {"status":"healthy"}

# Test frontend serves
curl -I http://localhost:12348/
# Expected: 200 OK, Content-Type: text/html

# Test API endpoint (if you have test credentials)
# curl http://localhost:12348/api/auth/status

# Check logs
docker logs mygarage-bun-test

# Cleanup
docker stop mygarage-bun-test
docker rm mygarage-bun-test
```

**Success Criteria:**
- ✅ Docker build completes without errors
- ✅ Build time equal or faster than Node.js version
- ✅ Image size smaller than Node.js version
- ✅ Container starts successfully
- ✅ Health check passes
- ✅ Frontend HTML serves on port 8686
- ✅ API endpoints respond correctly
- ✅ No errors in container logs

**Document Results:**
```bash
cat >> MIGRATION_BASELINE.md << 'EOF'

## Post-Migration (Bun 1.3.4)

### Build Times
- bun install: _____ seconds (vs npm ci: _____ seconds)
- bun run build: _____ seconds (vs npm run build: _____ seconds)
- Docker build total: _____ seconds (vs Node.js: _____ seconds)

### Docker Image Sizes
- Frontend builder stage: _____ MB (vs Node.js: _____ MB)
- Final production image: _____ MB (vs Node.js: _____ MB)

### Test Results
- All tests: PASS / FAIL
- Container startup: PASS / FAIL
- Health check: PASS / FAIL

Date: $(date)
EOF
```

#### Step 1.5: Update GitHub Actions CI/CD

**File:** [.github/workflows/ci.yml](.github/workflows/ci.yml)

**Changes:** Replace Node.js setup with Bun setup in frontend test job

```yaml
name: CI

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main, develop ]

jobs:
  test-backend:
    name: Backend Tests
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Set up Python 3.14
        uses: actions/setup-python@v6
        with:
          python-version: '3.14'
          cache: 'pip'
          cache-dependency-path: 'backend/pyproject.toml'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -e backend/[dev]

      - name: Run pytest with coverage
        run: |
          cd backend
          pytest tests/unit/ -v --tb=short --cov=app --cov-report=term-missing

  test-frontend:
    name: Frontend Tests
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      # CHANGED: Use Bun instead of Node.js
      - name: Set up Bun
        uses: oven-sh/setup-bun@v2
        with:
          bun-version: '1.3.4'

      # CHANGED: Bun install instead of npm ci
      - name: Install dependencies
        run: |
          cd frontend
          bun install --frozen-lockfile

      # CHANGED: Use bun run for type checking
      - name: Run TypeScript type checking
        run: |
          cd frontend
          bun run type-check

      # CHANGED: Use bun run for linting
      - name: Run linter
        run: |
          cd frontend
          bun run lint

      # CHANGED: Use bun test instead of npm test
      - name: Run tests
        run: |
          cd frontend
          bun test --run

  docker-build-test:
    name: Docker Build Test
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      # UNCHANGED: Docker build now uses Bun via Dockerfile
      - name: Build Docker image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          tags: mygarage:test
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

**File:** [.github/workflows/docker-build.yml](.github/workflows/docker-build.yml)

**Changes:** None required - workflow uses Dockerfile which now has Bun

**Optional:** Add workflow label to indicate Bun usage

```yaml
# Add to metadata (line 75, after label section)
LABEL org.opencontainers.image.frontend.builder="bun-1.3.4"
```

**Git Checkpoint:**
```bash
git add .github/workflows/ci.yml
git commit -m "ci: migrate frontend CI to Bun 1.3.4

- Replace setup-node with oven-sh/setup-bun@v2
- Update install: npm ci → bun install --frozen-lockfile
- Update scripts: npm run → bun run / bun test
- Docker build workflow unchanged (uses Dockerfile)
"
```

#### Step 1.6: Update Docker Compose (Optional)

**File:** [compose.yaml](compose.yaml)

**Changes:** Add label to track Bun version (optional)

```yaml
services:
  mygarage-dev:
    container_name: mygarage-dev
    build:
      context: .
      dockerfile: Dockerfile
    deploy:
      resources:
        limits:
          memory: 512M
          pids: 150
    environment:
      TZ: ${TZ}
      DEBUG: "true"
      JWT_COOKIE_SECURE: "false"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8686/health"]
      interval: 20s
      timeout: 10s
      start_period: 40s
      retries: 3
    image: mygarage:dev
    labels:
      dev.environment: "test"
      dev.project: "mygarage"
      dev.frontend.runtime: "bun-1.3.4"  # ← ADD (optional)
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    ports: ["12347:8686"]
    restart: unless-stopped
    security_opt: [no-new-privileges:true]
    volumes:
      - ./data:/data
    networks:
      - default
      - monitoring

networks:
  default:
  monitoring:
    external: true
```

**Test Docker Compose:**
```bash
cd /srv/raid0/docker/build/mygarage

# Build with compose
docker compose build

# Start service
docker compose up -d

# Check status
docker compose ps
docker compose logs -f mygarage-dev

# Test endpoints
curl http://localhost:12347/health

# Stop when done
docker compose down
```

**Git Checkpoint:**
```bash
git add compose.yaml
git commit -m "chore(compose): add Bun runtime label

- Add dev.frontend.runtime label for tracking
"
```

#### Step 1.7: Update Documentation

**File:** Create/Update `DEVELOPMENT.md`

```bash
cd /srv/raid0/docker/build/mygarage
```

**Create/Update [DEVELOPMENT.md](DEVELOPMENT.md):**

```markdown
# MyGarage Development Guide

## Prerequisites

### Required
- **Bun:** 1.3.4+ ([Install guide](https://bun.sh/docs/installation))
- **Python:** 3.14+
- **Docker:** 24.0+ with Compose plugin
- **Git:** 2.40+

### Optional
- **PostgreSQL:** For production-like local development

## Local Development Setup

### Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Run database migrations
# (Add your migration commands here)

# Start backend dev server
python -m granian app.main:app --host 0.0.0.0 --port 8686 --reload
```

Backend runs at: http://localhost:8686

### Frontend Setup

```bash
cd frontend

# Install dependencies (fast!)
bun install

# Start dev server with HMR
bun dev
```

Frontend runs at: http://localhost:3000
API proxied to: http://localhost:8686

## Development Workflow

### Running Tests

**Frontend:**
```bash
cd frontend

# Run tests in watch mode
bun test

# Run tests once (CI mode)
bun test --run

# Run with coverage
bun test --coverage

# Open test UI
bun test --ui

# Type checking
bun run type-check

# Linting
bun run lint
```

**Backend:**
```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_auth.py -v
```

### Building for Production

**Frontend:**
```bash
cd frontend
bun run build
# Output: dist/
```

**Docker (Full Stack):**
```bash
# Build image
docker build -t mygarage:local .

# Or with Docker Compose
docker compose build
```

## Hot Module Replacement (HMR)

HMR is enabled by default in development mode. Changes to React components, CSS, and most code will update instantly without page refresh.

**What triggers HMR:**
- ✅ React component changes
- ✅ CSS/Tailwind changes
- ✅ TypeScript/JavaScript changes
- ✅ Hook changes

**What requires page refresh:**
- ⚠️ Changes to `main.tsx`
- ⚠️ Changes to `vite.config.ts`
- ⚠️ New dependencies added
- ⚠️ Environment variable changes

**HMR not working?**
```bash
# 1. Check Vite dev server is running on port 3000
# 2. Check browser console for errors
# 3. Try hard refresh: Ctrl+Shift+R (Cmd+Shift+R on Mac)
# 4. Restart dev server: Ctrl+C then bun dev
```

## Troubleshooting

### Bun Issues

**"Command not found: bun"**
```bash
# Install Bun
curl -fsSL https://bun.sh/install | bash

# Verify installation
bun --version
```

**"lockfile out of sync"**
```bash
# Regenerate lockfile
rm bun.lockb
bun install
```

**"Module not found" errors**
```bash
# Clean install
rm -rf node_modules bun.lockb
bun install
```

### Docker Issues

**"Frontend build failed"**
```bash
# Test frontend build locally first
cd frontend
bun run build

# If local build works but Docker fails, check:
# 1. Dockerfile COPY paths are correct
# 2. .dockerignore isn't excluding needed files
```

**"Container starts but frontend doesn't load"**
```bash
# Check if static files were copied
docker exec -it mygarage-dev ls -la /app/static

# Should see: index.html, assets/, etc.
```

## Environment Variables

### Backend (.env)
```env
DEBUG=true
DATABASE_PATH=/data/mygarage.db
JWT_SECRET=your-secret-key-here
JWT_COOKIE_SECURE=false  # Set true in production
```

### Frontend (Vite)
Environment variables prefixed with `VITE_` are exposed to frontend:

```env
VITE_API_BASE_URL=/api
```

Access in code:
```typescript
const apiUrl = import.meta.env.VITE_API_BASE_URL
```

## Migration from Node.js

This project was migrated from Node.js 25 to Bun 1.3.4 on 2024-12-08.

**If you need to rollback to Node.js:**
1. See `BUN_MIGRATION_PLAN.md` section "Rollback Plan"
2. Uncomment Node.js Dockerfile stage
3. Replace `bun.lockb` with `package-lock.json` from git history

## Additional Resources

- [Bun Documentation](https://bun.sh/docs)
- [Vite Documentation](https://vitejs.dev/)
- [React 19 Documentation](https://react.dev/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
```

**Git Checkpoint:**
```bash
git add DEVELOPMENT.md BUN_MIGRATION_PLAN.md MIGRATION_BASELINE.md
git commit -m "docs: add comprehensive development guide and migration docs

- Add DEVELOPMENT.md with Bun-specific instructions
- Document HMR setup and troubleshooting
- Add migration baseline tracking
- Include rollback instructions
"
```

#### Step 1.8: Final Phase 1 Testing

**Comprehensive Test Matrix:**

```bash
#!/bin/bash
# Save as: test-bun-migration.sh

set -e

echo "=========================================="
echo "MyGarage Bun Migration Test Suite"
echo "=========================================="
echo ""

cd /srv/raid0/docker/build/mygarage/frontend

# Test 1: Dependencies install
echo "Test 1: Dependencies install..."
rm -rf node_modules bun.lockb
time bun install --frozen-lockfile
echo "✅ Dependencies installed"
echo ""

# Test 2: Type checking
echo "Test 2: TypeScript type checking..."
bun run type-check
echo "✅ No type errors"
echo ""

# Test 3: Linting
echo "Test 3: ESLint..."
bun run lint
echo "✅ No lint errors"
echo ""

# Test 4: Tests
echo "Test 4: Running test suite..."
bun test --run
echo "✅ All tests passed"
echo ""

# Test 5: Build
echo "Test 5: Production build..."
rm -rf dist
time bun run build
test -f dist/index.html || (echo "❌ Build failed: index.html missing" && exit 1)
echo "✅ Build successful"
echo ""

# Test 6: Dev server startup (manual verification)
echo "Test 6: Dev server startup..."
echo "Starting dev server (will run for 10 seconds)..."
timeout 10 bun dev || true
echo "✅ Dev server started (manual verification required)"
echo ""

cd ..

# Test 7: Docker build
echo "Test 7: Docker build..."
time docker build -t mygarage:bun-test .
echo "✅ Docker build successful"
echo ""

# Test 8: Docker run
echo "Test 8: Docker container test..."
docker rm -f mygarage-bun-test 2>/dev/null || true
docker run -d \
  --name mygarage-bun-test \
  -p 12348:8686 \
  -e DEBUG=true \
  -e JWT_COOKIE_SECURE=false \
  mygarage:bun-test

echo "Waiting for container startup..."
sleep 15

# Health check
echo "Testing health endpoint..."
curl -f http://localhost:12348/health || (echo "❌ Health check failed" && exit 1)
echo "✅ Health check passed"

# Frontend serves
echo "Testing frontend..."
curl -f -I http://localhost:12348/ | grep "200 OK" || (echo "❌ Frontend not serving" && exit 1)
echo "✅ Frontend serving"

# Cleanup
docker stop mygarage-bun-test
docker rm mygarage-bun-test

echo ""
echo "=========================================="
echo "✅ ALL TESTS PASSED"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Push to feature branch"
echo "2. Create PR and verify CI passes"
echo "3. Manual testing in browser"
echo "4. Merge to main when ready"
```

**Run Test Suite:**
```bash
chmod +x test-bun-migration.sh
./test-bun-migration.sh
```

**Manual Testing Checklist:**

```markdown
# Manual Testing Checklist - Bun Migration

## Development Mode Testing
- [ ] `bun dev` starts without errors
- [ ] Frontend loads at http://localhost:3000
- [ ] HMR works (edit component, see instant update)
- [ ] API calls work (login, fetch data)
- [ ] Console has no errors
- [ ] Network tab shows no failed requests

## Production Build Testing
- [ ] `bun run build` completes successfully
- [ ] `dist/` contains expected files
- [ ] Bundle size is reasonable (~500KB-2MB gzipped)
- [ ] Source maps generated
- [ ] Chunk splitting works (vendor, charts, calendar, etc.)

## Docker Testing
- [ ] Docker build succeeds
- [ ] Container starts and passes health check
- [ ] Frontend loads at http://localhost:12347
- [ ] Login flow works
- [ ] CRUD operations work (vehicles, services, fuel)
- [ ] File uploads work (photos, attachments)
- [ ] Charts render correctly
- [ ] Calendar loads events
- [ ] No console errors in production build

## CI/CD Testing
- [ ] Push to feature branch
- [ ] GitHub Actions runs successfully
- [ ] test-frontend job passes
- [ ] test-backend job passes (unchanged)
- [ ] docker-build-test job passes
- [ ] Build time is acceptable

## Performance Verification
- [ ] Page load time < 2 seconds
- [ ] HMR updates < 500ms
- [ ] Navigation is smooth
- [ ] No performance regressions vs Node.js version
```

**Git Checkpoint:**
```bash
git add test-bun-migration.sh
git commit -m "test: add comprehensive Bun migration test suite

- Add automated test script for all migration aspects
- Include manual testing checklist
- Cover: install, build, test, Docker, CI/CD
"
```

---

### Phase 2: Optional Bun Native Features

**Timeline:** Evaluate after 2-4 weeks of Phase 1 stability
**Goal:** Replace third-party tools with Bun built-ins where beneficial
**Risk:** MEDIUM (requires configuration changes)

#### Option A: Replace Vite with Bun.build()

**Effort:** Medium (4-6 hours)
**Benefits:**
- Simpler configuration (fewer dependencies)
- Potentially faster builds
- Native TypeScript/JSX transpilation

**Drawbacks:**
- Manual HMR implementation needed
- Less mature than Vite
- More configuration code

**Implementation Preview:**

```typescript
// bun-build.ts (replaces vite.config.ts)
import type { BuildConfig } from 'bun';

const isDev = process.env.NODE_ENV !== 'production';

const config: BuildConfig = {
  entrypoints: ['./src/main.tsx'],
  outdir: './dist',
  target: 'browser',

  // Code splitting
  splitting: true,

  // Minification
  minify: !isDev,

  // Source maps
  sourcemap: isDev ? 'inline' : 'external',

  // Environment variables
  define: {
    'import.meta.env.PROD': JSON.stringify(!isDev),
    'import.meta.env.DEV': JSON.stringify(isDev),
  },

  // Naming
  naming: {
    entry: '[name].[hash].[ext]',
    chunk: '[name].[hash].[ext]',
    asset: 'assets/[name].[hash].[ext]',
  },
};

// Build
const result = await Bun.build(config);

if (!result.success) {
  console.error('Build failed:', result.logs);
  process.exit(1);
}

console.log('✅ Build successful');
```

**Dev Server with Bun:**

```typescript
// dev-server.ts
import { watch } from 'fs';
import { resolve } from 'path';

const server = Bun.serve({
  port: 3000,

  async fetch(req) {
    const url = new URL(req.url);

    // Proxy API requests
    if (url.pathname.startsWith('/api')) {
      return fetch(`http://localhost:8686${url.pathname}`, req);
    }

    // Serve static files
    const filePath = resolve('./src', url.pathname === '/' ? 'index.html' : url.pathname);
    const file = Bun.file(filePath);

    if (await file.exists()) {
      return new Response(file);
    }

    // SPA fallback
    return new Response(Bun.file('./index.html'));
  },

  // WebSocket for HMR
  websocket: {
    message(ws, message) {
      // Handle HMR messages
    },
  },
});

// Watch for file changes
watch('./src', { recursive: true }, (event, filename) => {
  console.log(`File changed: ${filename}`);
  // Trigger rebuild and HMR
});

console.log(`🚀 Dev server running at http://localhost:${server.port}`);
```

**Recommendation:** Only pursue this if:
- Vite becomes a bottleneck (unlikely)
- You want to reduce dependencies
- You're willing to maintain custom build logic

#### Option B: Replace Vitest with bun:test

**Effort:** Medium-High (6-10 hours to migrate all tests)
**Benefits:**
- Faster test execution (~2-3x)
- Simpler setup (no jsdom config)
- Native Bun integration

**Drawbacks:**
- Different API (all tests need updates)
- Less mature ecosystem
- Fewer plugins/extensions

**Implementation Preview:**

**Before (Vitest):**
```typescript
// src/components/__tests__/VehicleCard.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import VehicleCard from '../VehicleCard';

describe('VehicleCard', () => {
  it('renders vehicle information', () => {
    const vehicle = { id: '1', make: 'Toyota', model: 'Camry' };
    render(<VehicleCard vehicle={vehicle} />);
    expect(screen.getByText('Toyota Camry')).toBeInTheDocument();
  });
});
```

**After (bun:test):**
```typescript
// src/components/__tests__/VehicleCard.test.tsx
import { test, expect, mock } from 'bun:test';
import { render, screen } from '@testing-library/react';
import VehicleCard from '../VehicleCard';

test('VehicleCard renders vehicle information', () => {
  const vehicle = { id: '1', make: 'Toyota', model: 'Camry' };
  render(<VehicleCard vehicle={vehicle} />);
  expect(screen.getByText('Toyota Camry')).toBeDefined();
});
```

**Key Differences:**
- `describe/it` → `test()` (flat structure)
- `vi.fn()` → `mock()`
- `.toBeInTheDocument()` → `.toBeDefined()` (different matchers)

**Migration Steps:**
1. Replace Vitest imports with bun:test
2. Convert describe/it to test()
3. Update mocking syntax
4. Update assertions to use bun:test matchers
5. Remove Vitest config from vite.config.ts
6. Update package.json test script

**Recommendation:** Only pursue this if:
- You want maximum test speed
- You're starting a new test suite (not migrating existing)
- You don't rely on Vitest-specific plugins

#### Option C: Use Bun Native Transpiler (Easiest)

**Effort:** Low (1-2 hours)
**Benefits:**
- Remove `@vitejs/plugin-react-swc` dependency
- Slightly faster transpilation
- One less moving part

**Implementation:**

**Update [vite.config.ts](frontend/vite.config.ts):**

```typescript
import { defineConfig } from 'vite'
// Remove: import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [
    // Remove react() plugin - Bun handles JSX/TSX natively
    tailwindcss()
  ],

  // Tell Vite that Bun will handle transpilation
  esbuild: {
    loader: 'tsx',
    target: 'es2020',
  },

  // Rest unchanged...
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // ...
})
```

**Update [package.json](frontend/package.json):**

```json
{
  "devDependencies": {
    // Remove: "@vitejs/plugin-react-swc": "^4.2.2",
    // Keep everything else
  }
}
```

**Test:**
```bash
bun install  # Remove old dependency
bun dev      # Should still work
bun run build  # Should still work
```

**Recommendation:** Low-risk optimization to do in Phase 1 or Phase 2.

---

## Development Workflow Changes

### Before (Node.js)

```bash
# Install dependencies
npm ci
# ~30-60 seconds

# Start dev server
npm run dev
# ~3-5 seconds startup

# Run tests
npm test
# ~5-10 seconds for test suite

# Build production
npm run build
# ~15-30 seconds

# Type check
npx tsc --noEmit
# ~8-15 seconds
```

### After (Bun - Phase 1)

```bash
# Install dependencies
bun install
# ~2-5 seconds (10-25x faster)

# Start dev server
bun dev
# ~1-2 seconds startup (2-3x faster)

# Run tests
bun test
# ~3-6 seconds for test suite (1.5-2x faster)

# Build production
bun run build
# ~10-20 seconds (1.5-2x faster)

# Type check
bun run type-check  # or: bunx tsc --noEmit
# ~5-10 seconds (1.5-2x faster)
```

### New Bun-Specific Commands

```bash
# List installed packages
bun pm ls

# Check outdated packages
bun pm outdated

# Update specific package
bun add react@latest

# Run script (shorthand)
bun dev       # Same as: bun run dev
bun build     # Same as: bun run build
bun lint      # Same as: bun run lint

# Execute TypeScript directly (no build needed)
bun run ./scripts/some-script.ts

# Run one-off scripts
bunx <package>  # Like npx, but faster
```

---

## Testing Strategy

### Unit Tests (Frontend)

**Test Files:** `src/**/__tests__/*.test.tsx`

**Phase 1 (Keep Vitest):**
```bash
# Run all tests
bun test

# Run specific file
bun test src/components/__tests__/VehicleCard.test.tsx

# Watch mode
bun test --watch

# Coverage
bun test --coverage

# UI mode
bun test --ui
```

**Expected Behavior:**
- All existing tests pass unchanged
- Test execution is 1.5-2x faster
- Coverage reports generate correctly

### Integration Tests (Backend)

**No changes** - backend stays on Python/pytest

```bash
cd backend
pytest tests/ -v
```

### E2E Tests (If Applicable)

If you add E2E tests later (Playwright, Cypress):

```bash
# Install with Bun
bun add -D playwright
bunx playwright install

# Run E2E tests
bunx playwright test
```

### Docker Testing

**Build Test:**
```bash
# Test Docker build
docker build -t mygarage:test .

# Verify image size
docker images mygarage:test
```

**Runtime Test:**
```bash
# Start container
docker run -d --name test -p 12348:8686 mygarage:test

# Health check
curl http://localhost:12348/health

# Frontend check
curl http://localhost:12348/

# Cleanup
docker stop test && docker rm test
```

### CI/CD Testing

**GitHub Actions:** Runs automatically on push/PR

**Manual Trigger:**
```bash
# Push to trigger CI
git push origin feature/bun-migration

# Check workflow status
gh run list --branch feature/bun-migration

# View logs
gh run view <run-id> --log
```

---

## Docker Configuration

### Dockerfile Comparison

**Key Changes:**

| Aspect | Before (Node.js) | After (Bun) |
|--------|------------------|-------------|
| **Base Image** | `node:25-alpine` | `oven/bun:1.3.4-alpine` |
| **Image Size** | ~180 MB | ~90 MB |
| **Install Command** | `npm ci` | `bun install --frozen-lockfile` |
| **Build Command** | `npm run build` | `bun run build` |
| **Lockfile** | `package-lock.json` | `bun.lockb` |
| **Build Time** | ~60-90 seconds | ~30-45 seconds |

### Multi-Platform Builds

**If you need ARM64 support:**

```bash
# Build for multiple platforms
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t mygarage:multiarch \
  .

# Note: Bun supports both amd64 and arm64
```

### Build Optimization

**Layer Caching Strategy:**

```dockerfile
# Good: Copy lockfile first (cached unless dependencies change)
COPY frontend/package.json frontend/bun.lockb ./
RUN bun install --frozen-lockfile

# Then copy source (changes frequently, doesn't invalidate dependency layer)
COPY frontend/ ./
RUN bun run build
```

**BuildKit Features:**

```bash
# Enable BuildKit for faster builds
export DOCKER_BUILDKIT=1

# Use cache mounts (experimental)
docker buildx build \
  --cache-from type=gha \
  --cache-to type=gha,mode=max \
  -t mygarage:latest \
  .
```

---

## CI/CD Pipeline Updates

### GitHub Actions Workflows

#### Before (Node.js)

```yaml
- name: Set up Node.js 25
  uses: actions/setup-node@v4
  with:
    node-version: '25'
    cache: 'npm'
    cache-dependency-path: 'frontend/package-lock.json'

- name: Install dependencies
  run: cd frontend && npm ci

- name: Run tests
  run: cd frontend && npm test -- --run
```

#### After (Bun)

```yaml
- name: Set up Bun
  uses: oven-sh/setup-bun@v2
  with:
    bun-version: '1.3.4'

- name: Install dependencies
  run: cd frontend && bun install --frozen-lockfile

- name: Run tests
  run: cd frontend && bun test --run
```

### Caching Strategy

**Bun Lockfile Caching:**

```yaml
- name: Set up Bun
  uses: oven-sh/setup-bun@v2
  with:
    bun-version: '1.3.4'

# Automatic caching (oven-sh/setup-bun handles this)
# No manual cache configuration needed!

- name: Install dependencies
  run: bun install --frozen-lockfile
```

**Docker Build Caching:**

```yaml
- name: Set up Docker Buildx
  uses: docker/setup-buildx-action@v3

- name: Build Docker image
  uses: docker/build-push-action@v6
  with:
    context: .
    cache-from: type=gha
    cache-to: type=gha,mode=max
    # Uses GitHub Actions cache for Docker layers
```

### Expected CI/CD Performance

| Job | Before (Node.js) | After (Bun) | Improvement |
|-----|------------------|-------------|-------------|
| **Install Dependencies** | 30-45s | 3-8s | ~5-10x faster |
| **Type Checking** | 15-25s | 8-15s | ~1.5-2x faster |
| **Linting** | 8-15s | 5-10s | ~1.5x faster |
| **Unit Tests** | 20-30s | 10-20s | ~2x faster |
| **Build** | 30-45s | 20-30s | ~1.5x faster |
| **Total Frontend Job** | ~2-3 min | ~1-1.5 min | ~2x faster |

---

## Rollback Plan

### Emergency Rollback (Immediate)

**If production breaks after deployment:**

```bash
cd /srv/raid0/docker/build/mygarage

# Option 1: Revert to previous Docker image
docker pull mygarage:v2.14.1  # Last known good version
docker tag mygarage:v2.14.1 mygarage:latest
docker compose up -d --force-recreate

# Option 2: Rollback git and rebuild
git checkout backup/pre-bun-migration
docker compose build
docker compose up -d --force-recreate
```

### Controlled Rollback (Planned)

**If Bun migration proves problematic:**

#### Step 1: Revert Dockerfile

```dockerfile
# Uncomment the rollback section in Dockerfile (lines 30-36)
FROM node:25-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build
```

#### Step 2: Restore package-lock.json

```bash
cd frontend

# Get package-lock.json from git history
git show backup/pre-bun-migration:frontend/package-lock.json > package-lock.json

# Remove Bun artifacts
rm bun.lockb
rm -rf node_modules

# Reinstall with npm
npm ci
```

#### Step 3: Update package.json

```json
{
  // Remove Bun-specific field
  // "bun": "^1.3.4",  ← DELETE

  // Scripts remain the same (npm run works)
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    // ...
  }
}
```

#### Step 4: Rebuild and Deploy

```bash
# Test locally
npm ci
npm run build
npm test

# Build Docker
docker build -t mygarage:rollback .

# Deploy
docker compose down
docker compose up -d
```

#### Step 5: Revert CI/CD

```yaml
# .github/workflows/ci.yml
- name: Set up Node.js 25
  uses: actions/setup-node@v4
  with:
    node-version: '25'
    cache: 'npm'
    cache-dependency-path: 'frontend/package-lock.json'
```

### Rollback Checklist

```markdown
- [ ] Production service is down or degraded
- [ ] Identified Bun as root cause (not other changes)
- [ ] Created incident report/ticket
- [ ] Notified team/stakeholders
- [ ] Executed rollback steps (above)
- [ ] Verified production is healthy
- [ ] Documented issues for future investigation
- [ ] Scheduled post-mortem
```

---

## Performance Benchmarks

### Methodology

**Test Environment:**
- CPU: [Your CPU model]
- RAM: [Your RAM amount]
- Disk: [SSD/NVMe type]
- Docker: [Version]
- OS: Linux [kernel version]

**Benchmark Script:**

```bash
#!/bin/bash
# benchmark.sh - Run this before and after migration

set -e

echo "MyGarage Performance Benchmark"
echo "==============================="
echo ""

cd /srv/raid0/docker/build/mygarage/frontend

# Benchmark 1: Clean install
echo "1. Clean install (cold cache)..."
rm -rf node_modules bun.lockb package-lock.json
sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null  # Clear disk cache
START=$(date +%s%N)
bun install  # Or: npm ci
END=$(date +%s%N)
INSTALL_TIME=$(( (END - START) / 1000000 ))  # Convert to ms
echo "   Time: ${INSTALL_TIME}ms"
echo ""

# Benchmark 2: Cached install
echo "2. Cached install..."
rm -rf node_modules
START=$(date +%s%N)
bun install  # Or: npm ci
END=$(date +%s%N)
CACHED_INSTALL_TIME=$(( (END - START) / 1000000 ))
echo "   Time: ${CACHED_INSTALL_TIME}ms"
echo ""

# Benchmark 3: Production build
echo "3. Production build..."
rm -rf dist
START=$(date +%s%N)
bun run build  # Or: npm run build
END=$(date +%s%N)
BUILD_TIME=$(( (END - START) / 1000000 ))
echo "   Time: ${BUILD_TIME}ms"
echo ""

# Benchmark 4: Test suite
echo "4. Test suite..."
START=$(date +%s%N)
bun test --run  # Or: npm test -- --run
END=$(date +%s%N)
TEST_TIME=$(( (END - START) / 1000000 ))
echo "   Time: ${TEST_TIME}ms"
echo ""

# Benchmark 5: Type checking
echo "5. Type checking..."
START=$(date +%s%N)
bun run type-check  # Or: npx tsc --noEmit
END=$(date +%s%N)
TYPECHECK_TIME=$(( (END - START) / 1000000 ))
echo "   Time: ${TYPECHECK_TIME}ms"
echo ""

# Benchmark 6: Docker build
echo "6. Docker build..."
cd ..
docker builder prune -af
START=$(date +%s%N)
docker build -t mygarage:bench .
END=$(date +%s%N)
DOCKER_TIME=$(( (END - START) / 1000000 ))
echo "   Time: ${DOCKER_TIME}ms"

# Get image size
IMAGE_SIZE=$(docker images mygarage:bench --format "{{.Size}}")
echo "   Image size: ${IMAGE_SIZE}"
echo ""

# Summary
echo "==============================="
echo "SUMMARY"
echo "==============================="
echo "Clean install:     ${INSTALL_TIME}ms"
echo "Cached install:    ${CACHED_INSTALL_TIME}ms"
echo "Build:             ${BUILD_TIME}ms"
echo "Tests:             ${TEST_TIME}ms"
echo "Type check:        ${TYPECHECK_TIME}ms"
echo "Docker build:      ${DOCKER_TIME}ms"
echo "Docker image:      ${IMAGE_SIZE}"
echo ""

# Save results
cat > benchmark-results-$(date +%Y%m%d-%H%M%S).txt << EOF
Runtime: $(bun --version 2>/dev/null || npm --version)
Date: $(date)
Clean install: ${INSTALL_TIME}ms
Cached install: ${CACHED_INSTALL_TIME}ms
Build: ${BUILD_TIME}ms
Tests: ${TEST_TIME}ms
Type check: ${TYPECHECK_TIME}ms
Docker build: ${DOCKER_TIME}ms
Docker image: ${IMAGE_SIZE}
EOF

echo "Results saved to benchmark-results-*.txt"
```

**Run Benchmarks:**

```bash
# Before migration (Node.js)
./benchmark.sh > benchmark-node.txt

# After migration (Bun)
./benchmark.sh > benchmark-bun.txt

# Compare
diff -y benchmark-node.txt benchmark-bun.txt
```

### Expected Results

**Realistic Expectations (Based on Bun 1.3.4 Performance):**

| Metric | Node.js 25 | Bun 1.3.4 | Improvement |
|--------|------------|-----------|-------------|
| **Clean Install** | 30,000ms | 2,500ms | 12x faster |
| **Cached Install** | 15,000ms | 800ms | 19x faster |
| **Build** | 20,000ms | 12,000ms | 1.6x faster |
| **Tests** | 8,000ms | 4,500ms | 1.8x faster |
| **Type Check** | 10,000ms | 6,000ms | 1.6x faster |
| **Docker Build** | 90,000ms | 55,000ms | 1.6x faster |
| **Image Size** | 450 MB | 280 MB | 38% smaller |

**Note:** Actual results will vary based on:
- Hardware (CPU, disk speed)
- Network (for uncached installs)
- Dependency count
- Codebase size

---

## Troubleshooting Guide

### Issue: "Command not found: bun"

**Symptom:**
```bash
bun: command not found
```

**Solution:**
```bash
# Install Bun
curl -fsSL https://bun.sh/install | bash

# Reload shell
source ~/.bashrc  # or ~/.zshrc

# Verify
bun --version
```

---

### Issue: Bun Lockfile Out of Sync

**Symptom:**
```
error: lockfile out of sync
```

**Solution:**
```bash
# Option 1: Regenerate lockfile
rm bun.lockb
bun install

# Option 2: Force install
bun install --force

# Commit new lockfile
git add bun.lockb
git commit -m "chore: update bun lockfile"
```

---

### Issue: Module Not Found After Migration

**Symptom:**
```
Cannot find module 'some-package'
```

**Solution:**
```bash
# Clean install
rm -rf node_modules bun.lockb
bun install

# If still failing, check package.json for typos
cat package.json | grep some-package

# Verify package exists in registry
bun pm info some-package
```

---

### Issue: Docker Build Fails at Frontend Stage

**Symptom:**
```
ERROR [frontend-builder 5/6] RUN bun run build
```

**Solution:**
```bash
# Test build locally first
cd frontend
rm -rf dist
bun run build

# If local build works:
# 1. Check Dockerfile COPY paths
cat Dockerfile | grep COPY

# 2. Check .dockerignore isn't excluding needed files
cat .dockerignore

# 3. Rebuild with no cache
docker build --no-cache -t mygarage:debug .

# 4. Debug interactively
docker build -t mygarage:debug --target frontend-builder .
docker run -it mygarage:debug sh
# Inside container:
ls -la
bun run build
```

---

### Issue: HMR Not Working

**Symptom:**
- Changes don't reflect in browser
- Errors in console about WebSocket

**Solution:**
```bash
# 1. Check dev server is running on correct port
lsof -i :3000

# 2. Check browser console for errors
# (F12 → Console)

# 3. Check Vite config proxy settings
cat frontend/vite.config.ts | grep -A 10 server

# 4. Restart dev server
# Ctrl+C
bun dev

# 5. Hard refresh browser
# Ctrl+Shift+R (Windows/Linux)
# Cmd+Shift+R (Mac)

# 6. Clear Vite cache
rm -rf frontend/node_modules/.vite
bun dev
```

---

### Issue: Tests Failing After Migration

**Symptom:**
```
FAIL src/components/__tests__/VehicleCard.test.tsx
```

**Solution:**
```bash
# 1. Check test file imports
cat src/components/__tests__/VehicleCard.test.tsx | head -10

# 2. Verify test dependencies installed
bun pm ls | grep -E "(vitest|testing-library)"

# 3. Check Vitest config in vite.config.ts
cat frontend/vite.config.ts | grep -A 20 test

# 4. Run specific test with verbose output
bun test src/components/__tests__/VehicleCard.test.tsx --reporter=verbose

# 5. Clear test cache
rm -rf frontend/node_modules/.vitest
bun test
```

---

### Issue: Type Errors After Migration

**Symptom:**
```
error TS2307: Cannot find module '@/components/VehicleCard'
```

**Solution:**
```bash
# 1. Check tsconfig.json paths
cat frontend/tsconfig.json | grep -A 5 paths

# 2. Verify file exists
ls frontend/src/components/VehicleCard.tsx

# 3. Restart TypeScript server in VSCode
# Cmd+Shift+P → "TypeScript: Restart TS Server"

# 4. Regenerate TypeScript build info
rm frontend/tsconfig.tsbuildinfo
bun run type-check
```

---

### Issue: Vite Plugin Errors with Bun

**Symptom:**
```
Error: Plugin "@vitejs/plugin-react-swc" is not compatible with Bun
```

**Solution:**
```bash
# Option 1: Update plugin versions
bun update @vitejs/plugin-react-swc

# Option 2: Use Bun native transpiler (see Phase 2, Option C)
# Remove @vitejs/plugin-react-swc from vite.config.ts

# Option 3: Revert to @vitejs/plugin-react (non-SWC)
bun remove @vitejs/plugin-react-swc
bun add -D @vitejs/plugin-react

# Update vite.config.ts:
# import react from '@vitejs/plugin-react'
```

---

### Issue: Docker Container Exits Immediately

**Symptom:**
```bash
docker ps  # Container not running
docker logs mygarage-dev  # Shows exit error
```

**Solution:**
```bash
# 1. Check logs for error
docker logs mygarage-dev 2>&1 | tail -50

# 2. Run container interactively
docker run -it --rm \
  -p 12347:8686 \
  -v $(pwd)/data:/data \
  mygarage:dev \
  sh

# Inside container, test command manually:
granian --interface asgi --host 0.0.0.0 --port 8686 --workers 1 app.main:app

# 3. Check backend dependencies (Python)
docker exec -it mygarage-dev pip list

# 4. Verify static files copied
docker exec -it mygarage-dev ls -la /app/static
```

---

### Issue: Performance Regression vs Node.js

**Symptom:**
- Bun build slower than expected
- Runtime performance worse

**Solution:**
```bash
# 1. Run benchmark script to quantify
./benchmark.sh

# 2. Check Bun version
bun --version  # Should be 1.3.4+

# 3. Verify no debug flags
# Check package.json scripts don't have --inspect or similar

# 4. Profile build
bun run build --profile

# 5. Check Docker layer caching
docker history mygarage:dev | head -20

# 6. Compare bundle sizes
ls -lh frontend/dist/*.js

# If significantly worse:
# - Revert to Node.js (see Rollback Plan)
# - File issue with benchmark data
```

---

## Post-Migration Checklist

### Immediate (Day 1)

- [ ] All tests pass locally (`bun test --run`)
- [ ] Type checking passes (`bun run type-check`)
- [ ] Linting passes (`bun run lint`)
- [ ] Production build succeeds (`bun run build`)
- [ ] Docker image builds successfully
- [ ] Docker container starts and passes health check
- [ ] Frontend loads in browser (dev mode)
- [ ] Frontend loads in browser (production mode)
- [ ] HMR works in development
- [ ] API calls work (login, CRUD operations)
- [ ] Git branch pushed to remote
- [ ] PR created with migration details

### Week 1

- [ ] CI/CD pipeline passes on all workflows
- [ ] Benchmark results documented
- [ ] Team members can run `bun dev` successfully
- [ ] No production incidents related to migration
- [ ] Performance is equal or better than Node.js
- [ ] No new errors in production logs
- [ ] Deployment to staging/dev successful
- [ ] Manual testing completed (see checklist above)

### Week 2-4

- [ ] Deployment to production successful
- [ ] Production monitoring shows no regressions
  - [ ] Page load times stable
  - [ ] API response times stable
  - [ ] Error rates unchanged
  - [ ] CPU/memory usage unchanged or better
- [ ] Team is comfortable with Bun workflow
- [ ] Documentation updated (README, wiki, etc.)
- [ ] No rollback needed
- [ ] Migration marked as complete

### Optional (Phase 2 Evaluation)

- [ ] 2-4 weeks of stability achieved
- [ ] Performance data collected
- [ ] Decision made on Phase 2 optimizations:
  - [ ] Replace Vite with Bun.build() (Y/N)
  - [ ] Replace Vitest with bun:test (Y/N)
  - [ ] Use Bun native transpiler (Y/N)
- [ ] If yes to any, create new tickets/issues
- [ ] Schedule Phase 2 implementation

---

## Additional Resources

### Documentation

- **Bun Official Docs:** https://bun.sh/docs
- **Bun API Reference:** https://bun.sh/docs/api
- **Bun Runtime:** https://bun.sh/docs/runtime
- **Bun Bundler:** https://bun.sh/docs/bundler
- **Bun Test Runner:** https://bun.sh/docs/cli/test

### Migration Guides

- **Node.js to Bun:** https://bun.sh/guides/ecosystem/node-to-bun
- **npm to bun:** https://bun.sh/docs/cli/install
- **Vite with Bun:** https://bun.sh/guides/ecosystem/vite
- **Vitest with Bun:** https://bun.sh/guides/test/vitest

### Community

- **Bun Discord:** https://bun.sh/discord
- **Bun GitHub:** https://github.com/oven-sh/bun
- **Bun Issues:** https://github.com/oven-sh/bun/issues

### Debugging

- **Bun Debug Mode:**
  ```bash
  DEBUG=* bun run build
  ```

- **Verbose Logging:**
  ```bash
  bun --verbose install
  bun --verbose run build
  ```

- **Bun Cache Location:**
  ```bash
  # Bun stores cache in:
  ~/.bun/install/cache/

  # Clear cache if needed:
  rm -rf ~/.bun/install/cache/
  ```

---

## Appendix A: File Changes Summary

### Files Created
- ✅ `BUN_MIGRATION_PLAN.md` (this file)
- ✅ `DEVELOPMENT.md` (developer guide)
- ✅ `MIGRATION_BASELINE.md` (performance tracking)
- ✅ `test-bun-migration.sh` (test automation)
- ✅ `benchmark.sh` (performance benchmarking)

### Files Modified
- ✅ `frontend/package.json` (added `bun` field, `type-check` script)
- ✅ `Dockerfile` (replaced Node.js with Bun builder)
- ✅ `.github/workflows/ci.yml` (updated frontend test job)
- ✅ `compose.yaml` (optional label addition)

### Files Added to Git
- ✅ `frontend/bun.lockb` (Bun lockfile)

### Files Removed from Git
- ✅ `frontend/package-lock.json` (npm lockfile)

### Files Unchanged
- ✅ `frontend/vite.config.ts`
- ✅ `frontend/tsconfig.json`
- ✅ `frontend/eslint.config.js`
- ✅ `frontend/tailwind.config.ts`
- ✅ `frontend/src/**/*` (all source code)
- ✅ `backend/**/*` (entire backend)
- ✅ `.github/workflows/docker-build.yml`

---

## Appendix B: Comparison with FamilyCircle

**Note:** You mentioned FamilyCircle is already using separate dev/prod workflows. Here's how to apply that pattern to MyGarage with Bun:

### FamilyCircle Pattern (Assumed)

```bash
# Development
cd frontend
npm install  # or bun install
npm run dev  # Frontend on :3000

cd ../backend
python -m granian app.main:app --reload  # Backend on :8080

# Production (Docker)
docker compose up -d  # Combined in one container
```

### Apply to MyGarage with Bun

**Development (Separate Processes):**

```bash
# Terminal 1: Backend
cd /srv/raid0/docker/build/mygarage/backend
python -m granian app.main:app \
  --host 0.0.0.0 \
  --port 8686 \
  --reload \
  --workers 1

# Terminal 2: Frontend
cd /srv/raid0/docker/build/mygarage/frontend
bun dev
# Runs on :3000, proxies /api to :8686
```

**Production (Docker - Already Set Up):**

```bash
# Already using Docker Compose with combined container
docker compose up -d
# Frontend built → /static
# Backend serves static + API on :8686
```

**Key Differences:**
- MyGarage: Already has proper HMR setup via Vite proxy ✅
- FamilyCircle: If not using HMR, could benefit from MyGarage's Vite config
- Both: Can use Bun for frontend, Python for backend

---

## Appendix C: Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2024-12-08 | Migrate to Bun 1.3.4 | Performance gains, smaller images, modern tooling |
| 2024-12-08 | Keep Vite in Phase 1 | Mature, proven, low-risk migration |
| 2024-12-08 | Keep Vitest in Phase 1 | Avoid rewriting test suite, Vitest works well with Bun |
| 2024-12-08 | Keep @vitejs/plugin-react-swc | Works fine, can evaluate Bun native in Phase 2 |
| 2024-12-08 | Use `bun install --frozen-lockfile` | Ensures reproducible builds like `npm ci` |
| TBD | Phase 2 evaluation | After 2-4 weeks of Phase 1 stability |

---

## Appendix D: Success Metrics

**How we'll measure success:**

### Performance Metrics
- ✅ Installation time: <10% of Node.js time (target: <5s vs ~50s)
- ✅ Build time: 1.2x-2x faster (target: <20s vs ~30s)
- ✅ Test time: 1.5x-2x faster (target: <10s vs ~15s)
- ✅ Docker image: <350MB (target: <300MB vs ~450MB)
- ✅ CI/CD runtime: <50% of previous (target: <90s vs ~180s)

### Reliability Metrics
- ✅ Zero production incidents related to Bun
- ✅ All tests pass consistently
- ✅ No HMR regressions
- ✅ Build reproducibility: 100% (lockfile + frozen installs)

### Developer Experience
- ✅ Team can use Bun commands within 1 day
- ✅ No development workflow regressions
- ✅ HMR still <500ms
- ✅ Positive feedback from team (survey/informal)

### Business Metrics
- ✅ No deployment delays due to migration
- ✅ No customer-facing issues
- ✅ Reduced CI/CD costs (less runner time)

---

## Conclusion

This migration plan provides a comprehensive, conservative approach to moving MyGarage from Node.js 25 to Bun 1.3.4. By following the phased approach:

1. **Phase 1** replaces only the runtime while keeping all proven tools (Vite, Vitest)
2. **Phase 2** optionally optimizes with Bun-native features after stability is proven
3. **Rollback Plan** ensures you can revert quickly if needed

**Expected Outcome:**
- 🚀 Faster development cycles (2-3x)
- 📦 Smaller production images (~40-60%)
- 💰 Reduced CI/CD costs
- 😊 Better developer experience
- ✅ Zero functionality changes

**Timeline:**
- Planning: 1 day (review this document)
- Implementation: 4-6 hours (execute Phase 1)
- Testing: 2-4 weeks (monitor stability)
- Phase 2: Optional, 4-8 hours per feature

**Risk Level:** **LOW** - with comprehensive testing and rollback plan

---

**Document Version:** 1.0
**Last Updated:** 2024-12-08
**Next Review:** After Phase 1 completion (2-4 weeks)

---

**Questions or Issues?**
1. Check [Troubleshooting Guide](#troubleshooting-guide)
2. Review [Bun Documentation](https://bun.sh/docs)
3. Open GitHub issue with benchmark data
4. Contact team for review

**Ready to proceed?** Start with Phase 1, Step 0.1: Pre-Migration Preparation ⬆️
