# MyGarage Database Migrations

This directory contains database migration scripts for MyGarage.

## Overview

MyGarage uses a custom migration system with automatic discovery and tracking. Migrations are Python scripts that execute database schema changes in a controlled, versioned manner. **All migrations must be portable across SQLite and PostgreSQL.**

## Running Migrations

### Automatic Execution

Migrations run **automatically** on application startup via the `init_db()` function in `database.py`. When you start MyGarage, pending migrations are detected and executed automatically. The runner passes its database engine to each migration.

### Manual Execution

To run all pending migrations manually:

```bash
cd /srv/raid0/docker/build/mygarage/backend
python -m app.migrations.runner
```

## Migration Naming Convention

Format: `NNN_descriptive_name.py`
- `NNN`: Three-digit sequential number (001, 002, 003...)
- `descriptive_name`: Snake_case description

Example: `048_add_new_feature.py`

## Creating a New Migration

1. Create file in `/srv/raid0/docker/build/mygarage/backend/app/migrations/`
2. Use next sequential number
3. Implement `upgrade(engine=None)` function (must accept engine parameter)
4. Use `inspect(engine)` for schema introspection (never `PRAGMA` or `sqlite_master`)
5. Use dialect-aware DDL for table creation (see template below)

### Migration Template

```python
"""Brief description of migration."""

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _get_fallback_engine():
    """Build a SQLite engine from environment for standalone execution."""
    db_path = os.environ.get("DATABASE_PATH")
    if db_path:
        return create_engine(f"sqlite:///{db_path}")
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    return create_engine(f"sqlite:///{data_dir / 'mygarage.db'}")


def upgrade(engine=None):
    """Perform migration."""
    if engine is None:
        engine = _get_fallback_engine()

    with engine.begin() as conn:
        inspector = inspect(engine)

        # Check if already applied (idempotency)
        existing_columns = {col["name"] for col in inspector.get_columns("table_name")}

        if "new_column" in existing_columns:
            print("  → Migration already applied, skipping")
            return

        # Perform migration
        conn.execute(text("""
            ALTER TABLE table_name
            ADD COLUMN new_column VARCHAR(50)
        """))

        print("✓ Migration completed successfully")


if __name__ == "__main__":
    upgrade()
```

### Table Creation Template (dialect-aware)

```python
def upgrade(engine=None):
    if engine is None:
        engine = _get_fallback_engine()

    is_postgres = engine.dialect.name == "postgresql"
    pk_type = "SERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_postgres else "DATETIME"

    with engine.begin() as conn:
        inspector = inspect(engine)

        if not inspector.has_table("new_table"):
            conn.execute(text(f"""
                CREATE TABLE new_table (
                    id {pk_type},
                    name VARCHAR(100) NOT NULL,
                    created_at {ts_type} DEFAULT CURRENT_TIMESTAMP
                )
            """))
```

## PostgreSQL Compatibility Rules

1. **Never use** `PRAGMA` or `sqlite_master` — use `inspect(engine)` instead
2. **Never hardcode** database URLs — accept `engine` parameter from the runner
3. **Use `SERIAL PRIMARY KEY`** on PostgreSQL, `INTEGER PRIMARY KEY AUTOINCREMENT` on SQLite
4. **Use `TIMESTAMP`** on PostgreSQL, `DATETIME` on SQLite
5. **Use `ON CONFLICT DO NOTHING`** instead of `INSERT OR IGNORE`
6. **Use `RETURNING id`** on PostgreSQL, `last_insert_rowid()` on SQLite for PK retrieval
7. **For table rebuilds** (constraint changes), use `ALTER TABLE ... DROP/ADD CONSTRAINT` on PostgreSQL

## Migration Tracking

Migrations are tracked in the `schema_migrations` table:
- `id`: Auto-increment primary key
- `migration_name`: Filename without extension
- `applied_at`: Timestamp

## Best Practices

1. **Idempotency**: Always check if migration already applied
2. **Logging**: Print clear progress messages
3. **Validation**: Verify migration results
4. **Backup**: Backup database before running migrations
5. **Testing**: Test on copy of production database first
6. **Portability**: Test on both SQLite and PostgreSQL

## Troubleshooting

### Migration fails with "column already exists"

The migration is idempotent — safe to run again. This is harmless.

### Container won't start after migration

Check backend logs:
```bash
docker logs mygarage-backend-dev --tail 50
```

If migration failed, restore from backup and investigate the error.

## Additional Resources

- SQLAlchemy Inspector: https://docs.sqlalchemy.org/en/20/core/inspection.html
- SQLite ALTER TABLE docs: https://www.sqlite.org/lang_altertable.html
- PostgreSQL ALTER TABLE docs: https://www.postgresql.org/docs/current/sql-altertable.html
- MyGarage migration runner: `app/migrations/runner.py`
