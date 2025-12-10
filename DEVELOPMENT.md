# MyGarage Development Guide

This guide covers local development setup for MyGarage using **Bun 1.3.4** for the frontend and **Python 3.14** for the backend.

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
- **Bun** 1.3.4+ ([Installation guide](https://bun.sh/docs/installation))
- **Python** 3.14+
- **Git**

### Optional
- **Docker** & **Docker Compose** (for containerized development)
- **PostgreSQL** 16+ (if not using SQLite)

### Installing Bun

```bash
# macOS/Linux/WSL
curl -fsSL https://bun.sh/install | bash

# Reload shell
source ~/.bashrc  # or ~/.zshrc

# Verify installation
bun --version  # Should show 1.3.4 or higher
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

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Run backend
python -m granian app.main:app --port 8686 --reload
```

Backend will be available at: http://localhost:8686

### 3. Frontend Setup

In a new terminal:

```bash
cd frontend

# Install dependencies (very fast with Bun!)
bun install

# Start development server
bun dev
```

Frontend will be available at: http://localhost:3000

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
bun test

# Run tests in watch mode
bun test --watch

# Run tests with UI
bun test --ui

# Run tests with coverage
bun test --coverage

# Type checking
bun run type-check

# Linting
bun run lint
```

### Technology Stack

- **Runtime**: Bun 1.3.4
- **Bundler**: Vite 7.2.4
- **Test Runner**: Vitest 4.0.15
- **Framework**: React 19
- **Language**: TypeScript 5.9.3
- **Styling**: Tailwind CSS 4
- **Icons**: Lucide React
- **Charts**: Recharts
- **Forms**: React Hook Form + Zod
- **Router**: React Router Dom 7

### Project Structure

```
frontend/
├── src/
│   ├── components/       # Reusable React components
│   ├── pages/           # Page components (routes)
│   ├── hooks/           # Custom React hooks
│   ├── lib/             # Utilities and API clients
│   ├── types/           # TypeScript type definitions
│   └── __tests__/       # Test files
├── public/              # Static assets
├── dist/                # Production build output
├── package.json         # Bun dependencies
├── bun.lock             # Bun lockfile
├── vite.config.ts       # Vite configuration
├── tsconfig.json        # TypeScript configuration
└── tailwind.config.js   # Tailwind CSS configuration
```

### Development Workflow

1. **Start dev server**: `bun dev`
2. **Make changes** - HMR will automatically reload
3. **Check types**: `bun run type-check`
4. **Run tests**: `bun test`
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
- **ESLint** for JavaScript/TypeScript linting
- **TypeScript** for type safety
- **Prettier** (via ESLint integration) for code formatting

Run linter before committing:
```bash
bun run lint
```

---

## Backend Development

### Commands

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run development server
python -m granian app.main:app --port 8686 --reload

# Run with debug mode
DEBUG=true python -m granian app.main:app --port 8686 --reload

# Run tests
pytest

# Run tests with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/unit/test_vehicles.py

# Database migrations
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Technology Stack

- **Framework**: FastAPI
- **Database ORM**: SQLAlchemy 2.0+
- **Migrations**: Alembic
- **ASGI Server**: Granian (Rust-based, fast)
- **Authentication**: JWT + Argon2 password hashing
- **OAuth2/OIDC**: Authlib
- **Testing**: pytest + pytest-asyncio
- **Database**: SQLite (default) or PostgreSQL

### Project Structure

```
backend/
├── app/
│   ├── api/             # API route handlers
│   ├── models/          # SQLAlchemy models
│   ├── schemas/         # Pydantic schemas
│   ├── core/            # Core functionality (auth, config, db)
│   ├── services/        # Business logic
│   └── main.py          # FastAPI application entry
├── tests/
│   ├── unit/            # Unit tests
│   └── integration/     # Integration tests
├── alembic/             # Database migrations
├── pyproject.toml       # Python dependencies
└── pytest.ini           # Pytest configuration
```

### API Documentation

Interactive API docs:
- **Swagger UI**: http://localhost:8686/docs
- **ReDoc**: http://localhost:8686/redoc
- **OpenAPI JSON**: http://localhost:8686/openapi.json

### Database

Default: SQLite at `./data/mygarage.db`

To use PostgreSQL:
```bash
export MYGARAGE_DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/mygarage"
python -m granian app.main:app --port 8686 --reload
```

### Environment Variables

```bash
# Database
MYGARAGE_DATABASE_URL=sqlite+aiosqlite:///./data/mygarage.db

# Authentication
MYGARAGE_AUTH_MODE=local  # Options: none, local, oidc
MYGARAGE_JWT_SECRET_KEY=auto-generated-on-first-run

# OIDC (if using auth_mode='oidc')
MYGARAGE_OIDC_ISSUER=https://auth.example.com/application/o/mygarage/
MYGARAGE_OIDC_CLIENT_ID=your-client-id
MYGARAGE_OIDC_CLIENT_SECRET=your-client-secret

# Debug
DEBUG=true
```

---

## Docker Development

### Build and Run

```bash
# Build image
docker build -t mygarage:dev .

# Run with Docker Compose
docker compose up -d

# View logs
docker compose logs -f

# Rebuild and restart
docker compose up -d --build --force-recreate

# Stop
docker compose down
```

### Development with Docker

The Dockerfile uses a multi-stage build:
1. **Frontend stage**: Bun 1.3.4-alpine builds the React app
2. **Backend stage**: Python 3.14-slim installs backend dependencies
3. **Production stage**: Combines built frontend + backend

### Docker Compose

The `compose.yaml` includes:
- Port mapping: `12347:8686`
- Volume mount: `./data:/data`
- Health checks
- Debug mode enabled
- Resource limits

### Testing Docker Build

```bash
# Build
docker build -t mygarage:test .

# Run
docker run -d \
  --name mygarage-test \
  -p 8687:8686 \
  -v $(pwd)/data:/data \
  -e DEBUG=true \
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
bun test

# Run tests in watch mode
bun test --watch

# Run tests with UI
bun test --ui

# Run with coverage
bun test --coverage

# Run specific test file
bun test src/components/VehicleCard.test.tsx
```

Test framework: **Vitest** with:
- `@testing-library/react` for component testing
- `@testing-library/jest-dom` for DOM assertions
- `jsdom` for DOM environment

### Backend Tests

```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test
pytest tests/unit/test_vehicles.py::test_create_vehicle

# Run integration tests only
pytest tests/integration/
```

### End-to-End Tests

Currently manual. Automated E2E tests (Playwright/Cypress) coming soon.

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
# Regenerate lockfile
rm bun.lock
bun install

# Or force install
bun install --force
```

#### "Module not found" errors
```bash
# Clean install
rm -rf node_modules bun.lock
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
# Run type checking
bun run type-check

# Check specific file
bunx tsc --noEmit src/path/to/file.tsx
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
# Reinstall dependencies
pip install --force-reinstall -e ".[dev]"
```

#### Migration errors
```bash
# Reset database (WARNING: deletes data)
rm data/mygarage.db
alembic upgrade head
```

### Docker Issues

#### Port already in use
```bash
# Change port in compose.yaml
ports: ["8687:8686"]  # Use 8687 instead

# Or stop conflicting container
docker ps | grep 12347
docker stop <container-name>
```

#### Build fails
```bash
# Clear Docker cache
docker builder prune

# Rebuild from scratch
docker compose build --no-cache
```

#### Container won't start
```bash
# Check logs
docker compose logs mygarage-dev

# Common issues:
# 1. Database permission errors - run: sudo chown -R 1000:1000 ./data
# 2. Port conflict - change port in compose.yaml
# 3. Missing environment variables - check .env file
```

---

## Performance

### Bun Benefits

Compared to Node.js 25 + npm:
- **10-25x faster** package installation (19s vs 30-60s)
- **1.5-2x faster** build times (2.8s vs 4-5s)
- **~40-60% smaller** Docker images
- **~2x faster** CI/CD pipeline

### Build Optimization

The frontend uses manual chunk splitting for optimal caching:
- `react-vendor.js` - React, React DOM, React Router
- `charts.js` - Recharts
- `calendar.js` - React Big Calendar + date-fns
- `ui.js` - Lucide React + Sonner
- `forms.js` - React Hook Form + Zod
- `utils.js` - Axios

This means when you update application code, users only download changed chunks, not the entire vendor bundle.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes
4. Run tests: `bun test && pytest`
5. Run linters: `bun run lint`
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

**Last Updated**: 2025-12-09 (Bun 1.3.4 migration)
