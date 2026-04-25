# MyGarage E2E

Hard release gate. Builds the production image, brings up Postgres + 2
mygarage instances (PG-backed and SQLite-backed) from scratch, and runs an
HTTP smoke test against both.

## Run

```bash
bash tests/e2e/run.sh
```

Takes ~90 seconds on a warm Docker cache. Always tears down on exit.

## What it covers

- All migrations apply cleanly on a fresh PG and SQLite DB. (The #038/#048
  fresh-install bugs in v2.26.3 would have been caught here.)
- Auth flow: register → login → CSRF.
- One full CRUD round-trip on fuel records, including the canonical-SI
  `price_per_unit` round-trip that broke in v2.26.3.

## What it does NOT cover

- Frontend rendering — that's Playwright territory, not run here.
- Every endpoint, every permission edge case, every DB driver quirk — those
  are unit / integration test material.

## Knobs

- `E2E_KEEP=1` — on failure, leave the stack up so you can poke at it.
  Run `bash tests/e2e/teardown.sh` when done.
- `E2E_NO_BUILD=1` — reuse the existing `mygarage:e2e` image instead of
  rebuilding. Useful when iterating on smoke.py.

## Where it runs

- **Locally** as the release-coordinator's hard gate before tagging.
- **In CI** (planned) as a job that fires on every push to `main`.
