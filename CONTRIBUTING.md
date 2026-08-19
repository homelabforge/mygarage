# Contributing to MyGarage

Thanks for your interest in contributing to MyGarage!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/mygarage.git`
3. Create a branch: `git checkout -b feat/short-description`
4. Make your changes and test locally (see below)
5. Commit using the [conventional commit](#commits) format
6. Push and open a Pull Request

CI must pass before a PR can merge. Tests, linting, type-checks, PostgreSQL
migrations, and CodeQL all run automatically on your PR.

## Development Setup

See [DEVELOPMENT.md](DEVELOPMENT.md) for prerequisites and how to run the
backend and frontend locally.

## Translations

Adding or improving a language is the easiest way to help. See
[TRANSLATING.md](TRANSLATING.md) for the step-by-step guide. Current coverage
is tracked in [TRANSLATIONS.md](TRANSLATIONS.md).

## Code Style

Formatting and linting are enforced in CI; run them before pushing.

**Backend (Python):** [Ruff](https://docs.astral.sh/ruff/) for formatting and
linting, type hints on all functions, and `async`/`await` for database work.

```bash
cd backend
ruff format . && ruff check . && pytest
```

**Frontend (React/TypeScript):** ESLint (flat config), 2-space indentation, and
functional components with explicit return types. The UI is built from the
shared primitives in `src/components/ui/` (`Button`, `Card`, `Input`, `Select`,
`Field`, …) and semantic theme tokens (`text-text`, `bg-surface-2`,
`border-border`, …) that drive the accent-based light/dark theme. Reuse them
rather than hardcoding colours or adding new tokens.

```bash
cd frontend
bun run lint && bun run type-check && bun run test:run
bun run validate:translations
```

**API contract:** if you changed backend routes or Pydantic schemas, regenerate
the OpenAPI schema and the TypeScript types. CI's *API Types Freshness* check
fails when the committed files drift from the backend:

```bash
cd frontend
bun run generate:api   # needs uv + backend deps (see DEVELOPMENT.md)
```

Commit both `src/types/openapi.json` and `src/types/api.generated.ts`.

To run every gate exactly as CI does (needs Docker + Bun): `bin/ci-check`.

## Commits

Use the conventional commit format:

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `refactor:` code refactoring
- `test:` adding or updating tests
- `chore:` maintenance

```bash
git commit -m "feat: add vehicle export to CSV"
git commit -m "fix: correct fuel economy for partial fill-ups"
```

## Bug Reports

Open a [GitHub Issue](https://github.com/homelabforge/mygarage/issues) with a
clear description, steps to reproduce, expected vs actual behaviour, and
environment details (OS, Docker version, browser).

## Feature Requests & Questions

Open a [GitHub Discussion](https://github.com/homelabforge/mygarage/discussions)
to propose a feature before building it, or ask in our
[Discord community](https://discord.gg/6XttnVgG).
