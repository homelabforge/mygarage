# Pre-migration PG baselines

These are `pg_dump --schema-only --inserts` snapshots of the PostgreSQL
schema as it existed *before* a given migration was added. Tests for
migration N load `pre_N.sql` into a clean PG schema, run migration N,
and assert the expected post-state.

## Why

The repo's existing PG migration tests in `pg_migration_path_test.py`
run `Base.metadata.create_all()` first and then invoke the migrations.
That reliably hides bugs: by the time the migration under test runs,
every column or constraint it tries to add already exists (because
SQLAlchemy's `create_all` materializes the *current* model schema,
which is post-everything). The migration's idempotency guard then
short-circuits, so the literal SQL strings in the migration never run
against PostgreSQL.

Migration 054 shipped with two such bugs (`DATETIME` column type and
`ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS`). Both passed every
existing test on PG. The baseline framework closes that gap: by loading
a real pre-054 schema, migration 054's `ALTER TABLE` statements *do*
have to run, and bugs in their SQL surface immediately.

## Files

| File | Boundary |
|---|---|
| `pre_054.sql` | Schema after migrations 001..053. Represents what an existing v2.26.4 user's PG database looks like. |

When migration 055 ships, generate `pre_055.sql` the same way (using
the v2.27.0 tag as the worktree).

## How to regenerate

The baseline is generated from a worktree at the last-stable git tag
because that worktree's `Base.metadata` reflects pre-N column state. If
we used the current source's `create_all`, post-N columns would already
exist and the resulting dump would be useless for testing N.

### One-time prep

```bash
# Worktree at the last release tag before the new migration
git worktree add /tmp/mygarage-baseline v2.26.4
```

### Generate

```bash
# 1. Bring up the PG sidecar
MYGARAGE_TEST_UID=$(id -u) MYGARAGE_TEST_GID=$(id -g) \
    docker compose -f docker-compose.test.yml -p mygarage-test \
    up -d postgres-test

# 2. Wait for healthy
until docker compose -f docker-compose.test.yml -p mygarage-test \
        ps postgres-test --format '{{.Health}}' | grep -q healthy; do
    sleep 2
done

# 3. From the v2.26.4 worktree, run create_all + migrations 001..053
docker run --rm \
    --network mygarage-test_mygarage-test \
    --user "$(id -u):$(id -g)" \
    -v /tmp/mygarage-baseline/backend:/app:ro \
    -e PYTHONPATH=/app \
    -e UV_PROJECT_ENVIRONMENT=/opt/venv \
    -e HOME=/tmp \
    -e MYGARAGE_TEST_MODE=true \
    -e MYGARAGE_SECRET_KEY=test-secret-key \
    -e DATA_DIR=/tmp \
    mygarage-test:local \
    python -c "
from pathlib import Path
from sqlalchemy import create_engine, text
from app.database import Base
import app.models  # __init__.py exports
import app.models.user
import app.models.audit_log
import app.models.oidc_pending_link
import app.models.toll
import app.models.maintenance_template
from app.migrations.runner import MigrationRunner

url = 'postgresql+psycopg2://mygarage:testpass@postgres-test:5432/mygarage_test'
engine = create_engine(url)
with engine.begin() as conn:
    conn.execute(text('DROP SCHEMA IF EXISTS public CASCADE'))
    conn.execute(text('CREATE SCHEMA public'))
Base.metadata.create_all(engine)
engine.dispose()

runner = MigrationRunner(url, Path('/app/app/migrations'))
runner.run_pending_migrations()
"

# 4. Dump schema + schema_migrations data, strip psql metacommands +
#    search_path SET (see "Why strip search_path" below).
docker run --rm \
    --network mygarage-test_mygarage-test \
    -e PGPASSWORD=testpass \
    postgres:16-alpine \
    sh -c "pg_dump --schema-only --no-owner --no-acl --no-privileges \
              -h postgres-test -U mygarage -d mygarage_test \
        && pg_dump --data-only --inserts --table=schema_migrations \
              -h postgres-test -U mygarage -d mygarage_test" \
    2>/dev/null \
    | python3 -c "
import sys
for line in sys.stdin:
    if line.startswith('\\\\restrict ') or line.startswith('\\\\unrestrict '):
        continue
    if 'set_config' in line and 'search_path' in line:
        continue
    sys.stdout.write(line)
" > backend/tests/migrations/baselines/pre_054.sql

# 5. Tear down
docker compose -f docker-compose.test.yml -p mygarage-test down -v
git worktree remove /tmp/mygarage-baseline
```

### Why explicit model imports

The list of `import app.models.*` lines exists because `app/models/__init__.py`
historically only re-exported a subset of model classes. Other tables (Users,
AuditLog, OIDCPendingLink, Toll, MaintenanceTemplate) are referenced only
from service modules. Without these explicit imports, those classes never
get registered with `Base.metadata` and `create_all` skips their tables —
which then makes the early FK-bearing migrations fail.

When the model package's `__init__.py` is updated to re-export everything,
the explicit imports above can be removed.

### Why `--inserts` for schema_migrations

The default pg_dump format uses `COPY ... FROM stdin` followed by `\.` — a
psql metacommand, not SQL. The baseline loader runs the dump through
SQLAlchemy's `exec_driver_sql`, which only accepts standard SQL.
`--inserts` produces portable `INSERT INTO ... VALUES (...)` rows.

### Why strip `search_path`

pg_dump emits `SELECT pg_catalog.set_config('search_path', '', false);` at
the top of both schema and data sections, defensively pinning the search
path to nothing so reloads can't accidentally hit a wrong schema. The
third arg `false` is `is_local=false`, meaning the SET persists for the
*session*, not the transaction. Since psycopg2 pools connections, the
search path stays empty after the load — and subsequent test queries
that reference `schema_migrations` (no `public.` prefix) fail with
"relation does not exist". Stripping the line restores normal behavior.

## What the baseline contains

- All tables that v2.26.4 ships, with their full PG column types,
  constraints, indexes, sequences, and FK relationships.
- The `schema_migrations` table populated with rows for migrations
  001..053. This means when migration 054 runs against the loaded
  baseline, only 054 (and any later migration the test cares about)
  is treated as pending — earlier migrations are correctly skipped.

## What the baseline does NOT contain

- User data. The dump is `--schema-only` plus `--data-only --table=schema_migrations`.
- Sensitive defaults. `MYGARAGE_SECRET_KEY=test-secret-key` is used
  for generation but no row references it.
- Nothing PG-version-specific beyond what `pg_dump` emits.
