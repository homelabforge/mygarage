# MyGarage Development Guide

This guide covers local development setup for MyGarage: **Bun** for the frontend and **Python** with **uv** for the backend. Versions aren't repeated here because they'd go stale; the pins live in `.bun-version`, `.nvmrc`, `frontend/package.json` and `backend/pyproject.toml`.

---

## Table of Contents
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Frontend Development](#frontend-development)
- [Backend Development](#backend-development)
- [Docker Development](#docker-development)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required
- **Bun**, the version in `.bun-version` ([Installation guide](https://bun.sh/docs/installation))
- **Python**, the version in `requires-python` (`backend/pyproject.toml`)
- **uv** ([Installation guide](https://docs.astral.sh/uv/getting-started/installation/)); it installs the backend from `backend/uv.lock`
- **Git**

### Optional
- **Node**, the major version in `.nvmrc` (needed by `bin/ci-check` and the E2E tests)
- **Docker** & **Docker Compose** (for `bin/ci-check` and containerized development)
- **PostgreSQL** 16+ (if not using SQLite)

### Installing Bun

```bash
# macOS/Linux/WSL
curl -fsSL https://bun.sh/install | bash

# Reload shell
source ~/.bashrc  # or ~/.zshrc

# Verify installation
bun --version  # Should match .bun-version
```

For Windows (native), see: https://bun.sh/docs/installation#windows

---

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/homelabforge/mygarage.git
cd mygarage
```

### 2. Backend Setup

```bash
cd backend

# Install dependencies (into backend/.venv)
uv sync --extra dev

# Keep local data in ./data (gitignored) instead of the container's /data
mkdir -p ../data
export MYGARAGE_DATA_DIR="$(cd ../data && pwd)"
export MYGARAGE_ATTACHMENTS_DIR="$MYGARAGE_DATA_DIR/attachments"
export MYGARAGE_PHOTOS_DIR="$MYGARAGE_DATA_DIR/photos"
export MYGARAGE_DOCUMENTS_DIR="$MYGARAGE_DATA_DIR/documents"
export MYGARAGE_DATABASE_URL="sqlite+aiosqlite:///$MYGARAGE_DATA_DIR/mygarage.db"

# Run backend
uv run python -m granian --interface asgi --port 8686 app.main:app
```

Backend will be available at: http://localhost:8686 (check http://localhost:8686/health).
There's no auto-reload (Granian's `--reload` needs the `granian[reload]` extra, which
isn't installed), so restart it after a backend change.

### 3. Frontend Setup

In a new terminal:

```bash
cd frontend

# Install dependencies
bun install

# Start development server
bun dev
```

Frontend will be available at: http://localhost:3000. The Vite dev server proxies
`/api` and `/health` to the backend on port 8686 (`VITE_API_URL` overrides that).

---

## Frontend Development

### Commands

```bash
# Install dependencies
bun install

# Start dev server with HMR
bun dev

# Build for production
bun run build

# Preview production build
bun run preview

# Run tests
bun run test:run

# Run tests in watch mode
bun run test

# Run tests with UI
bun run test:ui

# Run tests with coverage
bun run test:coverage

# Type checking
bun run type-check

# Linting
bun run lint
```

### Technology Stack

Versions are in `frontend/package.json`.

- **Runtime**: Bun
- **Bundler**: Vite (Rolldown)
- **Test Runner**: Vitest
- **Framework**: React 19
- **Language**: TypeScript
- **Styling**: Tailwind CSS 4, through the `@tailwindcss/vite` plugin (no `tailwind.config.js`)
- **Data fetching**: TanStack Query
- **i18n**: i18next
- **Icons**: Lucide React
- **Charts**: Recharts
- **Forms**: React Hook Form + Zod
- **Router**: React Router 7

### Project Structure

```
frontend/
├── src/
│   ├── components/      # Reusable React components
│   ├── pages/           # Page components (routes)
│   ├── hooks/           # Custom React hooks
│   ├── contexts/        # React context providers
│   ├── services/        # API client and service wrappers
│   ├── schemas/         # Zod schemas
│   ├── utils/           # Shared helpers
│   ├── locales/en/      # English strings (other languages are in public/locales/)
│   ├── types/           # Type definitions, including the generated API types
│   └── __tests__/       # Shared test helpers and app-wide tests
├── e2e/                 # Playwright specs
├── scripts/             # i18n and units gates, plus generators
├── public/              # Static assets and translated locales
├── package.json         # Bun dependencies
├── bun.lock             # Bun lockfile
├── vite.config.ts       # Vite configuration (Tailwind runs as a plugin here)
├── eslint.config.js     # ESLint flat config
└── tsconfig.json        # TypeScript configuration
```

### Development Workflow

1. **Start dev server**: `bun dev`
2. **Make changes** - HMR will automatically reload
3. **Check types**: `bun run type-check`
4. **Run tests**: `bun run test:run`
5. **Lint code**: `bun run lint`
6. **Build**: `bun run build`

### Hot Module Replacement (HMR)

Vite + Bun provides instant HMR:
- Component changes reload instantly
- State is preserved during updates
- CSS updates without full page reload

If HMR stops working:
```bash
# Clear Vite cache
rm -rf node_modules/.vite

# Restart dev server
bun dev
```

### Adding Dependencies

```bash
# Production dependency
bun add package-name

# Development dependency
bun add -d package-name

# Specific version
bun add package-name@1.2.3
```

### Code Style

The project uses:
- **ESLint** (flat config, `eslint.config.js`) for linting
- **TypeScript** for type safety

Run linter before committing:
```bash
bun run lint
```

---

## Backend Development

### Commands

Run these from `backend/`, with the `MYGARAGE_*` data-dir exports from Quick Start.

```bash
# Install dependencies
uv sync --extra dev

# Run development server
uv run python -m granian --interface asgi --port 8686 app.main:app

# Run with debug mode
MYGARAGE_DEBUG=true uv run python -m granian --interface asgi --port 8686 app.main:app

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=app --cov-report=term-missing

# Run specific test file
uv run pytest tests/unit/test_config.py

# Database migrations run on startup; no separate command.
# New ones go in app/migrations/ (see its README.md).
```

### Technology Stack

- **Framework**: FastAPI
- **Database ORM**: SQLAlchemy 2 (async)
- **Migrations**: custom scripts in `app/migrations/`, run on startup
- **ASGI Server**: Granian (Rust-based, fast)
- **Authentication**: JWT + Argon2 password hashing
- **OIDC**: joserfc for ID token verification
- **Testing**: pytest + pytest-asyncio
- **Database**: SQLite (default) or PostgreSQL

### Project Structure

```
backend/
├── app/
│   ├── routes/          # API route handlers
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── services/        # Business logic
│   ├── migrations/      # Database migrations (custom, not Alembic)
│   ├── tasks/           # Scheduled jobs
│   ├── utils/           # Shared helpers (units, time, CSV)
│   ├── config.py        # Settings from MYGARAGE_* env vars
│   ├── database.py      # Engine, sessions, startup migrations
│   └── main.py          # FastAPI application entry
├── tests/
│   ├── unit/            # Unit tests
│   ├── integration/     # Integration tests
│   └── migrations/      # Migration tests
├── tools/               # Maintenance, repair and dev scripts
├── pyproject.toml       # Python dependencies
└── pytest.ini           # Pytest configuration
```

### API Documentation

Interactive API docs:
- **Swagger UI**: http://localhost:8686/docs
- **ReDoc**: http://localhost:8686/redoc
- **OpenAPI JSON**: http://localhost:8686/openapi.json

### Database

Default: SQLite at `/data/mygarage.db` (the container path). For a local run, point
`MYGARAGE_DATABASE_URL` somewhere writable.

To use PostgreSQL:
```bash
export MYGARAGE_DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/mygarage"
uv run python -m granian --interface asgi --port 8686 app.main:app
```

### Environment Variables

The ones below are `MYGARAGE_`-prefixed fields in `backend/app/config.py`. The app
doesn't read a `.env` file itself.

```bash
# Database
MYGARAGE_DATABASE_URL=sqlite+aiosqlite:////absolute/path/to/mygarage.db

# Where data, the secret keys and uploads live (default /data and its subfolders)
MYGARAGE_DATA_DIR=/absolute/path/to/data
MYGARAGE_ATTACHMENTS_DIR=/absolute/path/to/data/attachments
MYGARAGE_PHOTOS_DIR=/absolute/path/to/data/photos
MYGARAGE_DOCUMENTS_DIR=/absolute/path/to/data/documents

# Debug (SQL echo and debug logging)
MYGARAGE_DEBUG=true
```

The auth mode (none, local or OIDC) and the OIDC client details aren't env vars. Set
them in Settings; they live in the database. The JWT secret is generated on first run
and kept in `secret.key` in the data directory (`/data` by default).

---

## Docker Development

### Build and Run

The repo ships `compose.example.yml`, which runs the published image. To run your
own checkout, build a local image and point a copy of it there. `compose.yaml` and
`data/` are both gitignored.

```bash
# Build image from your checkout
docker build -t mygarage:dev .

# Copy the example, then edit its image: line to mygarage:dev
cp compose.example.yml compose.yaml

# The container runs as UID 1000; give it ./data
mkdir -p data && sudo chown 1000:1000 data

# Run with Docker Compose
docker compose up -d

# View logs
docker compose logs -f mygarage

# Rebuild and restart after a change
docker build -t mygarage:dev . && docker compose up -d

# Stop
docker compose down
```

The app is then on http://localhost:8686.

### Development with Docker

The Dockerfile uses a multi-stage build:
1. **Frontend stage**: Bun `-slim` image builds the React app. Its version is the `BUN_VERSION` build arg; `bin/ci-check --all` passes `.bun-version`, and a plain `docker build` uses the Dockerfile default
2. **Backend stage**: Python `-slim` image installs backend dependencies
3. **Production stage**: Combines built frontend + backend and runs Granian as a non-root user

### Docker Compose

`compose.example.yml` includes:
- Port mapping: `8686:8686`
- Volume mount: `./data:/data`
- A health check on `/health`
- Commented-out reverse-proxy and settings-key environment variables

### Testing Docker Build

```bash
# Build
docker build -t mygarage:test .

# The container runs as UID 1000; give it ./data
mkdir -p data && sudo chown 1000:1000 data

# Run
docker run -d \
  --name mygarage-test \
  -p 8687:8686 \
  -v $(pwd)/data:/data \
  -e MYGARAGE_DEBUG=true \
  mygarage:test

# Test
curl http://localhost:8687/health

# Cleanup
docker stop mygarage-test
docker rm mygarage-test
```

---

## Testing

### Frontend Tests

```bash
cd frontend

# Run all tests
bun run test:run

# Run tests in watch mode
bun run test

# Run tests with UI
bun run test:ui

# Run with coverage
bun run test:coverage

# Run specific test file
bun run test:run src/components/__tests__/FamilyMemberCard.test.tsx
```

Test framework: **Vitest** with:
- `@testing-library/react` for component testing
- `@testing-library/jest-dom` for DOM assertions
- `jsdom` for DOM environment

### Backend Tests

```bash
cd backend

# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=app --cov-report=term-missing

# Run specific test
uv run pytest tests/integration/routes/test_vehicle.py::TestVehicleRoutes::test_create_vehicle

# Run integration tests only
uv run pytest tests/integration/
```

Host test runs can differ from CI (different package versions). `bin/ci-check` from
the repo root runs CI's gates in containers with CI's pins; `--backend` and
`--frontend` pick one side.

### End-to-End Tests

Playwright specs live in `frontend/e2e/` and run in CI on pushes to `main`,
`develop` and `release/**`, and on pull requests to `main` and `develop`.

Running them locally needs, beyond the setup above, `uv` on your PATH (the
config starts the backend with `uv run`), Node at the major version in `.nvmrc`,
and Playwright's Chromium:

```bash
cd frontend
bunx playwright install chromium --with-deps
bun run e2e        # or e2e:ui, e2e:headed, e2e:debug
```

The Playwright config starts four servers: the backend on port 8686 against a
throwaway SQLite database (`/tmp/mygarage-e2e.db`), the Vite dev server on port
3000, and, for the subpath specs, a production build served by a second backend
on 8687 behind a small proxy on 3001. Run plainly, it reuses anything already
listening on those ports, so stop anything on 8686, 8687, 3000 or 3001 first (a
dev backend or `bun run dev`), or the tests run against it. `bin/ci-check --all`
from the repo root runs them with `CI=true`, the way CI does: it stops with an
error instead of reusing a busy port.

---

## Troubleshooting

### Bun Issues

#### "Command not found: bun"
```bash
# Install Bun
curl -fsSL https://bun.sh/install | bash

# Reload shell
source ~/.bashrc  # or ~/.zshrc

# Verify
bun --version
```

#### "lockfile out of sync"
```bash
# Update the lockfile in place and commit it; don't delete bun.lock
bun install
```

#### "Module not found" errors
```bash
# Clean install (keep bun.lock)
rm -rf node_modules
bun install
```

### Frontend Issues

#### HMR not working
1. Check Vite dev server is running on port 3000
2. Check browser console for errors
3. Try hard refresh: `Ctrl+Shift+R` (Cmd+Shift+R on Mac)
4. Restart dev server: `Ctrl+C` then `bun dev`
5. Clear Vite cache: `rm -rf node_modules/.vite && bun dev`

#### Build fails
```bash
# Clear cache and rebuild
rm -rf dist node_modules/.vite
bun install
bun run build
```

#### Type errors
```bash
# Run type checking (uses the project's tsconfig files)
bun run type-check
```

### Backend Issues

#### Database locked
```bash
# SQLite database is locked by another process
# Stop all MyGarage instances and try again

# Or use PostgreSQL instead
export MYGARAGE_DATABASE_URL="postgresql+asyncpg://..."
```

#### Import errors
```bash
# Reinstall dependencies from the lockfile
uv sync --extra dev --reinstall
```

#### Migration errors
```bash
# Reset a LOCAL dev database (WARNING: deletes data). Migrations rerun on the next start.
rm "$MYGARAGE_DATA_DIR"/mygarage.db*
```

### Docker Issues

#### Port already in use
```bash
# Change the host port in compose.yaml
ports: ["8687:8686"]  # Use 8687 instead

# Or find and stop whatever holds 8686
docker ps --filter publish=8686
docker stop <container-name>
```

#### Build fails
```bash
# Clear Docker cache
docker builder prune

# Rebuild from scratch
docker build --no-cache -t mygarage:dev .
```

#### Container won't start
```bash
# Check logs
docker compose logs mygarage

# Common issues:
# 1. Database permission errors - run: sudo chown -R 1000:1000 ./data
# 2. Port conflict - change port in compose.yaml
# 3. A setting you meant to pass - check environment: in compose.yaml
```

---

## Performance

### Build Optimization

The frontend splits its vendor code into named chunks (React, charts, calendar, UI,
forms, query, i18n and so on; the list is `codeSplitting` in `frontend/vite.config.ts`),
so an app-code change only invalidates the chunks that changed, not the whole vendor
bundle.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes
4. Run the gates: `bin/ci-check` from the repo root (needs Docker, Bun and Node; see [Prerequisites](#prerequisites))
5. Run linters: `cd frontend && bun run lint`
6. Commit changes: `git commit -m "feat: add my feature"`
7. Push: `git push origin feature/my-feature`
8. Create Pull Request

### Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `chore:` - Maintenance tasks
- `test:` - Test changes
- `refactor:` - Code refactoring
- `ci:` - CI/CD changes

---

## Additional Resources

- **Wiki**: https://github.com/homelabforge/mygarage/wiki
- **Bun Documentation**: https://bun.sh/docs
- **Vite Documentation**: https://vite.dev
- **FastAPI Documentation**: https://fastapi.tiangolo.com
- **React Documentation**: https://react.dev

---

**Last Updated**: 2026-11-08
